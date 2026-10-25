# Spec: Tail-risk–optimised portfolio parametric insurance (v2)

Status: draft v0.2 (2026-10-25). Lives at `docs/SPEC.md` in this repository since the bootstrap issue (MAR-6).

> **Scope of this file:** the *how* (method, architecture, data contract, standards). Goals, priorities, plan, decisions and status live in **Linear**, starting at the [Program hub](https://linear.app/marc-prinzing/project/program-hub-1b757250497c). Where this file and Linear disagree on any of those, Linear wins and this file gets fixed.
Name (D1, decided 2026-10-25): repository and distribution **`parametric-insurance-design`**. The import package is `parametric_insurance_design`, and the docs convention is `import parametric_insurance_design as pid`. The core CLI is `parametric-insurance-design`. The name is free on PyPI and GitHub as of 2026-10-25.

---

## 1. Purpose

The master's thesis framework (`parametric-insurance-framework`, tagged `thesis-v1`) introduced two ideas:

1. **Tail-risk–optimised payout design**: a weighted CVaR/expected-shortfall objective for the uncovered loss, solved as a linear program (LP).
2. **Portfolio-level calibration**: payout functions calibrated jointly over a portfolio (individual, cluster and integrated scopes), so assets can cover each other.

v2 turns this into publishable work. The outputs are **equally important**:

- **Interactive website and blog/LinkedIn posts.**
- **Showcase built on Climate Risk Commons (CRC) and VELO/CDT data**, in our own repository. The user holds a full licence.
- **Contribution to CLIMADA**, with no CRC code or data.
- **Peer-reviewed paper plus preprint.**

Everything sits on one foundation: a rework of the thesis code into a tested, installable core library, completed by the **core v1 features** (F-09 to F-12). The website v1, posts, CRC showcase and CLIMADA module are **early releases**: they ship once the core is ready and can take priority, because they publish sooner. The paper is the **scientific basis and the longest track**. It runs in parallel, and its results feed v2 updates (robustness explorer, post 3, website v2).

### Guiding principles

- **Focus.** The paper is the hardened thesis method plus *one* extension: robust design under uncertainty. Everything else is parked (§9).
- **Publish early, claim carefully.** Until checkpoint C1 is Done, every external output:
  - presents the method and the tool;
  - states the setup of every number shown (portfolio, basis-risk model, pricing);
  - uses numbers from out-of-sample runs on the annual basis (F-09, F-10);
  - makes no general claim that tail optimisation outperforms.

  C1 decides which claims may be made after that.
- **Parity before change.** The new core must reproduce the thesis results before any method changes.
- **Streams share the core, never each other.** No CRC code in CLIMADA; no paper experiment code in the core.
- **No silent failures.** Solver failures, dropped entities and missing data raise or are reported. They are never skipped quietly.

---

## 2. Streams and projects

| Linear project | Role | Depends on |
|---|---|---|
| **Program hub** | Entry point and ground truth: mission, priorities, scheduling and publication rules, decision index, program status updates | — |
| **Foundation** (critical path) | New repository, core library, data contract, CLIMADA hazard pipeline, thesis parity, core v1 features (F5) | — |
| **Website & Blog** | v1 (early release): explorers and posts 1–2. v2: robustness explorer, post 3, relaunch with the preprint | v1: F-09, F-10. v2: Paper |
| **CRC Showcase** | Early release: CRC/VELO assets and hazards → core → showcase notebook, pipeline and report | Data contract, F-09, F-10 |
| **CLIMADA Contribution** | Early release: hazard-agnostic parametric design module for `climada_petals` (location to be agreed with maintainers) | Parity gate, F-10, F-12, maintainer alignment |
| **Paper** | Scientific basis, long track: checkpoint C1, portfolio and scenarios, robust design, manuscript | Core v1 features |

Linear (team MAR):
- [Program hub](https://linear.app/marc-prinzing/project/program-hub-1b757250497c): no issues; description plus status updates.
- [Foundation: core rework](https://linear.app/marc-prinzing/project/foundation-core-rework-c2e95573b935): MAR-5 to MAR-27, MAR-61, MAR-63 to MAR-73.
- [Paper: tail-risk portfolio design](https://linear.app/marc-prinzing/project/paper-tail-risk-portfolio-design-a1b097aab0cd): MAR-28 to MAR-40, MAR-62.
- [CRC Showcase](https://linear.app/marc-prinzing/project/crc-showcase-c284ea40b585): MAR-41 to MAR-46.
- [CLIMADA Contribution](https://linear.app/marc-prinzing/project/climada-contribution-010eedb5e9f8): MAR-47 to MAR-51.
- [Website & Blog](https://linear.app/marc-prinzing/project/website-and-blog-67c8433b43d0): MAR-52 to MAR-60, MAR-74.

Labels: Human, Gate, Decision, Spike, Research, Chore (plus Linear's Feature). Cross-project dependencies are Linear "blocked by" relations.

---

## 3. Known problems in thesis-v1 that v2 must fix

### 3.1 Code (handled in Foundation)

| # | Problem | v2 response |
|---|---|---|
| C1 | Optimisers live in the notebook as 9 near-duplicate solver methods (3 scopes × 3 objectives, ~1,200 lines) | Combinable building blocks: scope × payout structure × objective × pricing × constraints → one problem builder |
| C2 | Function defaults read notebook globals (`asset_config=experiment_config[...]`) | No global state. Typed config objects are passed explicitly |
| C3 | `_solve` swallows exceptions. Failed runs are skipped with `continue`. The KPI step drops groups with mismatched entity counts | Explicit `SolveResult` with status. Typed errors. Reports of dropped entities |
| C4 | Hard-coded and inconsistent paths (`risk-lab/...`, `_plausi.csv` output ≠ notebook input). Noise bounds 20/70 hard-coded | All paths and parameters come from config. One canonical artefact layout |
| C5 | Wide CSV with column-name conventions. Arrays stored as strings in result CSVs | Versioned Parquet data contract (§5) and a result store |
| C6 | `plotting.py` is 3,500 lines and mixes computation (sweeps re-optimise inside plot functions) | Computation → result store → plotting, as strictly separate layers |
| C7 | No tests, packaging or CI. Two clashing environments (CLIMADA: py3.11/numpy 1.26; analysis: numpy 2.4; CRC needs py≥3.12/pandas≥3) | uv workspace for core, viz and CRC. Separate pixi env for CLIMADA. CI on Python 3.11–3.13 |
| C8 | Config typos (`ATTACHEMENT`, `reshuffel`). `risk_loading` is in the config but unused | Validated config schema (pydantic). Unknown keys are errors |

### 3.2 Method (features in Foundation F5, analysis in the Paper)

| # | Problem | v2 response |
|---|---|---|
| M1 | In-sample evaluation: calibration and KPIs use the same events, and noise copies of a storm would leak across a row-level split | Train/test split by year blocks, with all copies of an event in the same fold. Block-bootstrap CIs (§6.1) |
| M2 | Basis risk is synthetic only: the index is the wind at the asset, the loss is a fixed curve of that same wind, and lognormal noise is the only mismatch | Separate the index from the loss: vulnerability uncertainty plus cat-in-a-circle index. The noise layer stays as a baseline (§6.3) |
| M3 | Probabilities are rescaled after the threshold filter, so the event distribution is conditional. β has no return-period meaning, and the budget is per event | Annual framing: event rates 1/Y, zero-loss years kept implicitly, CVaR over years. The old mode is kept for parity only (§6.2) |
| M4 | Budget = κ·E[L] with no risk/capital load | Pricing component with a cost-of-capital load, still an LP (§6.4) |
| M5 | Cross-coverage assumes a single risk owner, but this is not stated | State the use case as a single owner (corporate/municipal/sovereign) in the paper |

---

## 4. Repository and architecture

New repository (D1). The old repository is tagged `thesis-v1` and archived read-only, and the README links to it.

```
parametric-insurance-design/
├── packages/
│   ├── core/            # parametric-insurance-design: numpy, scipy, pandas, pyarrow, cvxpy, pydantic. NO hazard libraries
│   ├── viz/             # parametric-insurance-design-viz: matplotlib figures, reading only the result store
│   ├── crc/             # parametric-insurance-design-crc: CRC/VELO adapter (py>=3.12)
│   └── climada/         # parametric-insurance-design-climada: tracks → CLIMADA → EventSet (own pixi env, NOT a uv member)
├── research/            # paper: configs, run scripts, figure scripts, manuscript
├── showcase/crc/        # CRC showcase notebook, pipeline, report
├── site/                # static website, reading exported bundles
├── parity/              # thesis golden data and parity tests
└── docs/                # SPEC.md, ADRs, methodology notes
```

### 4.1 Environments

- **uv workspace** (core, viz, crc, research tooling). One lockfile. Core supports Python 3.11–3.13, numpy ≥1.26 and pandas ≥2.1 so that the CLIMADA env can import it.
- **pixi env** for `packages/climada`: CLIMADA from conda-forge, with core installed as an editable path dependency. Not in the uv lock, because CLIMADA's numpy pin would clash with CRC's pandas ≥3 requirement.
- Streams talk to each other only through **EventSet Parquet files** (§5). Example: the CLIMADA pipeline writes an EventSet, and the uv-side research code reads it.

### 4.2 Core modules (`packages/core/src/parametric_insurance_design/`)

The adapter and viz distributions import as `parametric_insurance_design_viz`, `parametric_insurance_design_crc` and `parametric_insurance_design_climada`.

| Module | Responsibility |
|---|---|
| `eventset.py` | `EventSet`: dense index and loss matrices, events, locations, metadata. Parquet I/O. Validation |
| `index.py` | Index definitions: point intensity, value-weighted cluster index. Precomputed custom indices (e.g. cat-in-a-circle from the CLIMADA adapter) |
| `payout.py` | `PayoutStructure` → basis matrix. `StepPayout` (breakpoints, monotone, capped) is implemented. Piecewise-linear is designed for but not built |
| `scopes.py` | `Individual`, `Portfolio`, `Cluster(strategy)`. Map assets to payout entities and set the aggregation level of the objective |
| `clustering.py` | Port of the thesis feature-plus-Ward clustering, as a pluggable strategy |
| `objectives.py` | `MSE`, `ExpectedUncovered`, `WeightedCVaR(alpha, beta)` (Rockafellar–Uryasev) |
| `pricing.py` | `PurePremium`, `CostOfCapitalLoad(rate, q)`. Std-dev load is optional (SOCP) |
| `problem.py` | Assembles a cvxpy problem from scope × payout × objective × pricing × constraints |
| `solve.py` | Solver policy (Clarabel → HiGHS/SCS fallback), `SolveResult`, typed `SolveError` |
| `evaluate.py` | KPIs: VaR/CVaR(U), E[U], RMSE, E[π]/E[L], correlation, exceedance curves on an event or annual basis |
| `splits.py` | Year-block train/test and k-fold. Copies of an event (noise/vulnerability draws) never cross folds |
| `robust.py` | Scenario-robust (R1) and distributionally robust (R2) wrappers (§6.5) |
| `experiment/` | Subpackage (ADR 0002 §8): `config.py` config schema, `runner.py` run executor and content-hashed caching, `store.py` result store, `sweeps.py` one-factor-at-a-time sweeps |
| `cli.py` | The `parametric-insurance-design` command (run, sweep, and later figures and export-site) |
| `noise.py` | Thesis noise layer (homo/heteroscedastic lognormal), bit-identical port for parity |
| `interfaces.py` | Shared contract types and ABCs: `Sample`, `Entity`, `ProblemSpec`, `DesignProblem`, `ProblemContext`, `PayoutStructure`, `Scope`, `Objective`, `Pricing`, `Constraint`, `SolveResult` (ADR 0002) |
| `basis.py` | `Basis` (`event_conditional`, `event`, `annual`) and `OutcomeMeasure`, the probability measure over outcomes shared by objectives, pricing and evaluation |
| `errors.py` | Error hierarchy under `ParametricInsuranceDesignError` |
| `records.py` | Typed result-store tables: `runs`, `entities`, `payouts`, `kpis`, `exceedance` |
| `constraints.py` | Extra constraints, e.g. the premium budget |

The contracts between these modules, and which Linear issue owns which file, are fixed in ADR 0002 (`docs/adr/0002-core-interfaces.md`).

### 4.3 Engineering standards

- Type hints throughout. Numpy-style docstrings (CLIMADA convention). ruff (lint + format) and pyright (basic).
- pytest with ≥85 % line coverage in `core`. Tutorial notebooks run in CI (nbmake). Notebooks never hold library logic.
- Determinism: one seeded `np.random.Generator` passed explicitly. Every result records the config hash, package versions and input-data checksum.
- Licences (D3, decided 2026-10-25; see ADR 0001). The licence boundary is the package boundary:

  | Package | Licence | Why |
  |---|---|---|
  | `core`, `viz`, `research/`, `site/` | **BSD-3-Clause** | The scientific Python norm (numpy, scipy, pandas). Permissive for industry reuse, and compatible with GPL/AGPL, so the adapters and the CLIMADA contribution can build on it |
  | `packages/climada` | **GPL-3.0-or-later** | Imports CLIMADA, which is GPLv3 (confirmed on the CLIMADA website) |
  | `packages/crc` | **AGPL-3.0-or-later** | Imports `crc-sdk` / `crc-framework`, which are AGPL-3.0-or-later on PyPI. Revisit if the owner's CRC agreement grants other terms for the SDK |

  Core and viz must never import an adapter, because that would pull copyleft terms into the permissive packages. The CLIMADA contribution itself goes upstream under CLIMADA's GPLv3.
- Data is never committed except small fixtures. Downloads go through scripts with checksums. IRIS/STORM licences are recorded in `docs/data-sources.md`.

---

## 5. Data contract: `EventSet` (schema v1)

Stored as one directory with Parquet tables and `metadata.json`.

| Table | Columns |
|---|---|
| `events` | `event_id` (str), `year` (int, simulation year, 0-based: `year ∈ [0, n_years)`), `rate` (float, annual frequency; default 1/Y), `draw_id` (int, noise/vulnerability draw; 0 if none), `scenario_id` (str) |
| `locations` | `location_id`, `lat`, `lon`, `value`, `name`, free metadata columns |
| `values` | long format: `event_id`, `draw_id`, `location_id`, `index` (float), `loss` (float) |
| `metadata.json` | schema version, hazard source and release, index definition and unit, loss unit/currency, `n_years`, scenario description, provenance (source checksums, producer package and version, created_at), licence |

In memory, an EventSet is a dense `(n_rows, n_locations)` index matrix and loss matrix, plus aligned event metadata. A threshold filter may drop rows only for speed. Rates are **never** rescaled, so dropped rows count as zero-loss mass.

**Draw rows.** When an event is expanded into `n` noise or vulnerability draws (`draw_id` 0 … n−1), each draw row carries `rate / n`, so the draws of one event together keep the event's rate. This is the thesis convention (1/(Y·n) per row when the event rate is 1/Y; confirmed bit-identical in MAR-10), and it makes `rates @ loss` the expected annual loss with no extra normalisation. On the annual basis, outcomes are per (year, `draw_id`): each draw is one simulated version of that year.

Migration: `parity/` holds the thesis `climada_transformed_loss_data.csv`, converted to an EventSet with a recorded checksum.

---

## 6. Method spec

§6.1–6.4 are implemented as **core v1 features** in Foundation (F-09 to F-12) and used by every output. Checkpoint C1 and §6.5 onwards are Paper work.

Notation: events e with rate w_e; years y = 1..Y (notation only: stored years are 0-based, `year ∈ [0, n_years)`, as in IRIS and the thesis; owner-confirmed 2026-10-25, MAR-89); locations i with index x_{e,i} and loss L_{e,i}; payout entities j with index ξ_{e,j}.
Step payout: π_{e,j} = Σ_k θ_{j,k}·1[ξ_{e,j} ∈ B_k], with θ ≥ 0, θ_{j,k} ≤ θ_{j,k+1} and θ_{j,k} ≤ cap_j. Breakpoints are uniform on [attachment, limit] (thesis default).
Scopes:
- individual: one problem per asset;
- portfolio: L_e = Σ_i L_{e,i} and π_e = Σ_j π_{e,j}, solved jointly;
- cluster: entities are clusters with ξ_{e,c} = value-weighted mean index.

### 6.1 Evaluation protocol (M1)
- Default split: the first 70 % of years train (stored years 0 … 0.7Y − 1), the rest test. Option: 5-fold by year blocks. Every draw of an event goes to the same fold.
- Report in-sample and out-of-sample KPIs, and their gap as a function of `n_bins` (overfitting diagnostic).
- CIs: block bootstrap over years (B = 1000 by default) for every reported KPI.
- **Acceptance:** each headline comparison reports out-of-sample KPI values with 90 % CIs.

### 6.2 Annual framing (M3)
- `basis = "annual"` (paper default): U_y = Σ_{e∈y} (L_e − π_e)^+. CVaR_β is taken over years, so β = 0.99 means the mean of the worst 1 % of years. Premium = annual E[π].
- `basis = "event_conditional"`: reproduces the thesis exactly (per-event U, rescaled probabilities). Used for parity only.
- Optional `basis = "event"`: per-event U with unrescaled rates.

### 6.3 Realistic basis risk (M2)
Each scenario combines one index definition with one source of loss truth:
- **Loss truth:** CLIMADA impact with **vulnerability uncertainty**. Sample impact-function parameters (Emanuel `v_half`, and `v_thresh` if needed) from a documented prior, stored as `draw_id`.
- **Index options:**
  - (a) wind at the asset (thesis);
  - (b) **cat-in-a-circle**: maximum Saffir–Simpson category of the track within radius r of the asset, computed from tracks in the CLIMADA adapter;
  - (c) optional: wind at the nearest grid node or a reference point at distance d.
- Baseline: index (a) plus the thesis noise layer (kept for comparison with the thesis).
- **Acceptance:** at least index (b) plus vulnerability uncertainty runs end to end, and the paper shows thesis-noise results next to it.

### 6.4 Loaded pricing (M4)
- Budget: Premium(π) ≤ κ·E[L].
- `PurePremium`: Premium = E[π].
- `CostOfCapitalLoad(r, q)`: Premium = (1−r)·E[π] + r·CVaR_q(π). Convex for r ∈ [0, 1], so it stays an LP. Paper defaults r = 0.06–0.10 and q = 0.99, with both swept.
- **Acceptance:** the headline results are reported under both pure and loaded pricing.

### Checkpoint C1 (go/narrative decision)
Using the core v1 features (§6.1–6.4), answer: *does the weighted-CVaR design still lower tail basis risk out of sample, under realistic basis risk and loaded pricing, compared with MSE and E[U] designs, for each scope?* The answer:
- fixes the paper's narrative (D4 venue, D6 R2 inclusion);
- decides which general claims the external outputs may make (publication rule, §1).

It does **not** gate the early releases. The CLIMADA module, website v1, posts 1–2 and the CRC showcase present the method and the tool.

### 6.5 Robust design under uncertainty (the extension)
Uncertainty is represented as scenario EventSets S_0 (reference) … S_K. Each is one of:
- (i) a hazard catalogue: IRIS vs. one more (D7: STORM or CLIMADA synthetic tracks from IBTrACS);
- (ii) a vulnerability parameter draw (§6.3);
- (iii) a climate scenario: CLIMADA's Knutson/Jewson TC climate scaling, 2050, SSP2-4.5 and SSP5-8.5;
- (iv) optional: a bootstrap resample of years.

- **R1 scenario-robust (primary):** min_θ max_k F_k(θ), with the premium priced on S_0. LP via epigraph: t ≥ F_k(θ) for all k, each F_k with its own Rockafellar–Uryasev auxiliaries.
- **R2 distributionally robust (secondary, decided at C1):** worst case of the objective over year weights q in an ambiguity ball around the empirical weights (total-variation → LP, χ² → SOCP). Radius ρ is swept.
- **Evaluation:**
  - leave-one-scenario-out: design on S_0, or robustly on the other scenarios, then test on the held-out S_k;
  - **price of robustness**: premium or E[U] cost versus tail basis risk saved under misspecification.
- **Acceptance:**
  - R1 is implemented and tested (with K = 1 it matches the nominal solution);
  - results cover at least uncertainty sources (i) and (iii);
  - a price-of-robustness figure exists for each scope.

### 6.6 Portfolio (D2, decided by spike P-05)
- **Requirements:**
  - single risk owner;
  - 25–200 assets inside the IRIS North Atlantic domain (US Gulf/East coast, Caribbean, Central America);
  - defensible values, or a documented value proxy.
- **Candidates:**
  - (a) a real company's assets from the **VELO/CDT database**: real coordinates and asset types; values need a proxy; may be anonymised in the paper;
  - (b) CLIMADA LitPop municipal/sovereign portfolio (fully open, which the CLIMADA tutorial needs anyway);
  - (c) Overture candidate locations.
- The thesis 9-asset Miami portfolio stays as the illustrative and parity case.

### 6.7 Testing the method
- **Analytical tests:**
  - with fine bins, no noise and a slack budget, the individual MSE solution equals the bin-wise conditional mean loss;
  - budget, monotonicity and cap always hold;
  - with α = 0, weighted-CVaR equals E[U];
  - R1 with K = 1 equals the nominal solution.
- **Parity tests (§7, F-06).**
- Regression tests on paper configs, using small fixtures.

---

## 7. Foundation milestones and acceptance

| ID | Milestone | Acceptance |
|---|---|---|
| F-01 | Repo bootstrap | uv workspace, CI (ruff, pyright, pytest; py3.11–3.13), pre-commit, licence, README, SPEC moved to `docs/` |
| F-02 | EventSet contract | Schema v1, Parquet I/O, validation, thesis CSV migrated with checksum |
| F-03 | Core engine | 3 scopes × 3 objectives from combinable blocks. Pure pricing. `SolveResult`/`SolveError`. Analytical tests pass. Solve-time baseline recorded |
| F-04 | Evaluation | KPIs on event_conditional and annual bases. Exceedance curves. Matches thesis `benchmarking.py` on fixtures |
| F-05 | Experiment runner | Pydantic config, OAT sweeps, content-hashed cache, Parquet result store, CLI `parametric-insurance-design run <config>` |
| F-06 | **Parity gate** | On the thesis event set, noise draws are bit-identical. All objective values and portfolio and asset KPIs match `benchmarking_kpis.csv` within 1e-4 relative (payout vectors compared loosely, because LP optima can be non-unique). Every gap is explained in `parity/REPORT.md` |
| F-07 | CLIMADA adapter | IRIS merge and track → wind → impact pipeline ported. Configurable paths. Writes an EventSet. Pixi env locked. Reproduces the thesis event-loss table |
| F-08 | Viz port | Thesis figure set regenerated from the result store (visual check plus figure-data CSVs) |
| F-09 | Out-of-sample evaluation (§6.1) | Year-block splits without leakage; block-bootstrap 90 % CIs on every KPI |
| F-10 | Annual basis (§6.2) | CVaR over years with return-period meaning; annual premium; parity mode kept |
| F-11 | Loaded pricing (§6.4) | Cost-of-capital load as an LP; r = 0 reduces to pure premium |
| F-12 | Realistic basis-risk inputs (§6.3) | Vulnerability draws (`draw_id`) and the cat-in-a-circle index in the CLIMADA adapter |

---

## 8. Other projects: milestones

**Paper** (the former P-01 to P-04 are now the Foundation core v1 features F-09 to F-12)
- Positioning: literature review, from day one
- **C1 checkpoint:** the analysis on F-09 to F-12
- P-05 Portfolio spike and build (§6.6, joint with R-01)
- P-06 Scenario EventSets (hazard catalogue, climate)
- P-07 Robust design R1, plus R2 if chosen at C1 (§6.5)
- P-08 Experiments and figures
- P-09 Manuscript, arXiv preprint, Zenodo code release with DOI

Positioning: Steinmann et al. 2023 (CLIMADA parametric framework), Maier & Scherer 2025/2026 (expectile payouts, single risk), arXiv 2409.16599 (diversification).

**CRC Showcase**
- R-01 Data inventory: CRC Open releases and the VELO/CDT asset database (fields, values, coverage). Licence and provenance record. Feeds P-05
- R-02 `parametric-insurance-design-crc` adapter: assets → `locations`; CRC hazard curves → per-location marginals
- R-03 Hazard comparison: IRIS/CLIMADA wind return levels vs. CRC cyclone curves at portfolio cells. CRC cyclone curves are pooled and scenario-independent, so this is model uncertainty, not climate change. Optionally feeds P-06
- R-04 Joint event set from CRC marginals with the IRIS empirical copula (rank reordering), for one hazard
- R-05 Showcase notebook, headless pipeline and report, following CRC conventions (provenance manifest, coverage exceptions visible)

**CLIMADA Contribution**
- K-01 Open a maintainer discussion (GitHub Discussion/issue) early, after F-03. Agree location (petals vs. core), solver dependency (cvxpy vs. scipy-HiGHS) and API style
- K-02 Module design ADR: works on `Hazard`, `Exposures`, `Impact` and `TCTracks`; index builders (centroid intensity, cat-in-a-circle); step payout; objectives; basis-risk metrics
- K-03 Implementation in a `climada_petals` fork: unit and integration tests, CLIMADA `.pylintrc`, AUTHORS entry. Starts after the parity gate, F-10 (annual basis), F-12 (cat-in-a-circle) and the accepted ADR. It does not wait for the paper
- K-04 Tutorial on open data only (LitPop plus synthetic tracks)
- K-05 PR to `develop` and the review cycle
- Excludes: CRC, VELO, robust-design research code (unless the maintainers ask for it), paper experiments

**Website & Blog**

v1, an early release that needs F-09 and F-10:
- W-01 Export bundle format: JSON slices for small grids and uncompressed Arrow IPC for larger tables (Quarto OJS reads both; Parquet is not a documented OJS format). Site skeleton in Quarto, deployed to GitHub Pages (D5, ADR 0003)
- W-02 Explorers from precomputed grids:
  - α/β → payout shape and exceedance curves;
  - portfolio cross-coverage map.
- W-03 Posts:
  - (1) why tail-optimised payouts: conceptual, can go out any time;
  - (2) the asset the optimiser drops (portfolio cover), with the cross-coverage explorer.
- W-04 Launch website v1

v2, after the paper:
- Robustness explorer (nominal vs. robust under scenarios)
- Post 3: designing for a climate you can't pin down
- W-05 Website v2 relaunch with the preprint and paper results

---

## 9. Out of scope (parked backlog)

- Piecewise-linear and data-driven breakpoints (the architecture supports them; no implementation).
- Per-asset fairness constraints ("price of fairness").
- New clustering methods (tail dependence, MILP joint assignment). The thesis clustering is only ported.
- Multi-hazard parametric covers in the paper (CRC showcase only, if at all).
- Live in-browser solver on the website.
- Wasserstein DRO over the index/loss support (non-convex with step payouts).

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| Tail advantage disappears out of sample or under loaded pricing | C1 checkpoint. A negative or nuanced result is still publishable ("when does tail-optimisation pay?") |
| Parity can't be reached exactly (degenerate LPs, solver versions) | Compare objective values and KPIs rather than payout vectors. Document the gaps |
| CLIMADA maintainers decline the module or ask for big changes | Talk to them early (K-01). The paper and core don't depend on acceptance |
| VELO/CDT assets lack values, or publishing them is sensitive | Value proxy plus anonymisation. LitPop fallback |
| Environment clash (CLIMADA vs. CRC) | Separate envs. Parquet contract as the only interface |
| Scope creep | §9 is binding. New ideas go to the backlog unless C1 calls for them |
| Early outputs claim more than C1 later supports | Publication rule (§1): method and tool only, setup stated, no general superiority claims before C1. The human approves every publication |
| Linear and the files drift apart | Linear is the source of truth for the what, when and status. The session start and end protocols (Program hub, `docs/ORCHESTRATION.md`) keep it current |

---

## 11. Decisions

Each decision's status and outcome is recorded on its **Linear issue**, which is canonical. Final technical outcomes also get an ADR.

| ID | Decision | Linear issue |
|---|---|---|
| D1 | Repository and package name: `parametric-insurance-design` (decided; ADR 0001) | MAR-5 |
| D2 | Paper portfolio source | MAR-30 |
| D3 | Licences: BSD-3-Clause core/viz, GPL-3.0-or-later CLIMADA adapter, AGPL-3.0-or-later CRC adapter (decided; ADR 0001, §4.3) | MAR-5 |
| D4 | Target venue (e.g. NHESS / Environment Systems and Decisions vs. Insurance: Mathematics and Economics / ASTIN) | MAR-29 (C1) |
| D5 | Website stack: Quarto + OJS on GitHub Pages (decided 2026-10-25; ADR 0003) | MAR-52 |
| D6 | Include R2 (distributionally robust) in the paper | MAR-29 (C1) |
| D7 | Second hazard catalogue: STORM, present climate v4, North Atlantic, CC0 (decided 2026-10-25; note in `research/notes/d7-second-hazard-catalogue.md`) | MAR-62 |

---

## 12. Delivery workflow (orchestrated agents)

The build is delegated to worker agents coordinated by an orchestrator agent, with the owner making all decisions.

- **Linear is the ground truth** for goals, priorities, plan, decisions and status. Every agent starts at the [Program hub](https://linear.app/marc-prinzing/project/program-hub-1b757250497c): its description and its latest status update. Before ending a session, the agent leaves Linear true.
- **Entry point:** the repo's [`CLAUDE.md`](../CLAUDE.md), which loads `AGENTS.md` and points the orchestrator to the runbook. The workspace `CLAUDE.md` outside the repo was the entry point until the repo existed; it now points here.
- **Scheduling across streams** (details in the runbook):
  - Foundation first;
  - then whatever brings the nearest public release forward;
  - at least one worker slot for the Paper track when it has ready work.

- **Worker agreement:** [`AGENTS.md`](../AGENTS.md). Covers sources of truth, one issue = one PR, file ownership, definition of done, escalation, and what agents never do.
- **Orchestrator runbook:** [`docs/ORCHESTRATION.md`](ORCHESTRATION.md). Covers status semantics (Todo = all blockers Done), the dispatch/review/merge loop, WIP limits, gates, the human queue and the start sequence.
- Both were drafted in the workspace's `repo-seed/` folder and live in this repository since the bootstrap (MAR-6), together with `CLAUDE.md` (`@AGENTS.md`).
- Linear labels:
  - **Human:** never completed by agents; only its "Agent may prepare" part may be delegated;
  - **Gate:** human sign-off unblocks downstream work;
  - **Decision:** a D1–D7 item, always also Human.
- **Contract-first:** MAR-61 fixes the core interfaces and a module ownership map (ADR 0002) before parallel implementation starts.
- Issues with sub-issues (MAR-17, MAR-18, MAR-19) are containers and are never dispatched themselves.
