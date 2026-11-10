# Spec: Tail-risk–optimised portfolio parametric insurance (v2)

Status: draft v0.2 (2026-10-25), updated for the CRC-first plan of 2026-11-05 (MAR-243). Lives at `docs/SPEC.md` in this repository since the bootstrap issue (MAR-6).

> **Scope of this file:** the *how* (method, architecture, data contract, standards). Goals, priorities, plan, decisions and status live in **Linear**, starting at the Program hub. Where this file and Linear disagree on any of those, Linear wins and this file gets fixed.
Name (D1, decided 2026-10-25): repository and distribution **`parametric-insurance-design`**. The import package is `parametric_insurance_design`, and the docs convention is `import parametric_insurance_design as pid`. The core CLI is `parametric-insurance-design`. The name is free on PyPI and GitHub as of 2026-10-25.

---

## 1. Purpose

The master's thesis framework (`parametric-insurance-framework`, tagged `thesis-v1`) introduced two ideas:

1. **Tail-risk–optimised payout design**: a weighted CVaR/expected-shortfall objective for the uncovered loss, solved as a linear program (LP).
2. **Portfolio-level calibration**: payout functions calibrated jointly over a portfolio (individual, cluster and integrated scopes), so assets can cover each other.

**Main goal (Marc, 2026-11-05).** After a meeting with the RiskThinking team, the program's main goal is a **generic parametric insurance module in Climate Risk Commons (CRC)**: `crc_sdk.parametric` in `crc-sdk`, with an exemplary notebook in `crc-docs`, contributed by PRs to RiskThinking's repositories. Its home in crc-sdk is confirmed. With it, users:

- create a parametric cover for a hazard and an asset;
- analyse its effectiveness on several metrics (overall coverage, tail coverage, basis risk, …) and under different scenarios;
- compare covers.

It is agnostic about the asset(s), the impact function(s), the scenario(s), the optimisation goal, the payout function type (linear, stepwise, piecewise linear, …) and its parametrisation, so users can build their own solutions. It comes in two steps:

1. **Phase 1:** the basic functionality and logic in CRC, plus the exemplary notebook.
2. **Phase 2 (continuous):** extensions, i.e. multi-hazard (multi-dimensional) covers, the portfolio approach (optimising for a portfolio goal, as in the thesis) and analysis under different scenarios.

The thesis's two ideas carry over as features of the module:

- **Tail-risk–optimised payout design:** the weighted CVaR of the uncovered loss is one of the module's optimisation goals, from Phase 1, next to MSE and expected uncovered loss.
- **Portfolio-level (joint) calibration:** the Phase 2 portfolio approach. A tail goal on the owner's total is the combination.

The module is built in forks of crc-sdk and crc-docs (D9, §11). Its design is ADR 0005 (D10, MAR-244), and its plan is in §8. It never imports this repository's core: the core is its reference implementation and test oracle, and parity is checked through golden fixtures the core exports (MAR-245). Phase 2 may use VELO/CDT assets for a real owner's book (MAR-41); the owner holds a full licence for CRC and VELO/CDT data. No CRC Open data is committed (CC BY-NC).

**Outputs and priorities** (Marc, 2026-11-05):

| Output | Linear project | Status |
|---|---|---|
| A generic parametric insurance module in crc-sdk and a showcase notebook in crc-docs, contributed upstream | CRC Contribution | **Main priority** |
| A CLIMADA parametric insurance module and its tutorial, motivated by the thesis, carrying both ideas (the objective and the calibration scope), with no CRC code or data | CLIMADA Contribution | Second priority, "to a lesser degree". The prototype (MAR-168) continues when CRC has no ready agent work |
| The core library `parametric-insurance-design` (0.1.0 on main, not on PyPI) | Foundation | Paused. The CRC module's reference implementation and test oracle |
| Website v1 and blog/LinkedIn posts | Website & Blog | Paused |
| Peer-reviewed paper plus preprint | Paper | Paused |

Paused projects get no new dispatches until Marc resumes them. Their open PRs stay as they are, and fixing a red `main` is still allowed.

**The research questions stay with the paper, which is paused: two co-equal stories, and their combination** (owner, 2026-10-31 and 2026-11-01). Each idea is a core story and must stand on its own, not only in combination:

- **RQ1, tail:** when does a tail-optimised (weighted-CVaR) design pay against MSE and E[U] designs?
- **RQ2, portfolio:** when does joint calibration (portfolio or cluster scope) pay against calibrating each asset on its own, under each objective (MSE, E[U], weighted CVaR)? The use case is one risk owner with many sites, who cares about the total shortfall, so sites can cover each other.
- **Combination (RQ1 × RQ2):** the combined design is a weighted-CVaR objective calibrated jointly across one owner's sites. The two ideas can be studied in isolation and in combination, depending on the use case. Each owner situation calls for one view:
  - one site: the tail view;
  - many sites with an average-fit mandate: the portfolio view;
  - many sites with a tail mandate: the combination.

C1 (§6), the paper (§8) and the posts report both stories and their combination, each with its own evidence.

The core is the thesis code reworked into a tested, installable library (Foundation, §7), completed by the **core v1 features** (F-09 to F-12). The paper is the scientific basis. When it resumes, its results feed the website's v2 (robustness explorer, post 3).

### Guiding principles

- **Focus.** The paper is the hardened thesis method plus *one* extension: robust design under uncertainty. Everything else is parked (§9).
- **Publish early, claim carefully.** The publication rule, decided at C1 (owner, 2026-11-01; MAR-29). Every external output (the CRC module's docs and notebook, the CLIMADA module's text, the website, posts, READMEs and docs pages):
  - presents the method and the tool;
  - states the setup of every number shown: portfolio or asset, basis, basis-risk model, pricing and split;
  - uses numbers from out-of-sample runs on the annual basis (F-09, F-10);
  - RQ1 (tail): makes only conditional, mechanism-based statements tied to a stated setup (e.g. "on this asset, under pure pricing, …"). No general claim that tail optimisation outperforms;
  - RQ2 (joint calibration): method only, meaning what joint calibration is and what it optimises. No comparative claim, in either direction;
  - the combination: any statement involving joint calibration follows the RQ2 rule;
  - links no private Linear pages.

  The owner revisits the RQ2 rule after the Florida rerun (MAR-152 item 4).
- **Parity before change.** The new core must reproduce the thesis results before any method changes.
- **Streams never share code with each other.** The CLIMADA stream and the paper build on the core. The CRC module imports nothing from it and is checked against its golden fixtures. The CLIMADA stream has no CRC code or data, and the core holds no paper experiment code.
- **No silent failures.** Solver failures, dropped entities and missing data raise or are reported. They are never skipped quietly.

---

## 2. Streams and projects

| Linear project | Role | Depends on |
|---|---|---|
| **Program hub** | Entry point and ground truth: mission, priorities, scheduling and publication rules, decision index, program status updates | — |
| **CRC Contribution: parametric insurance module** (main priority; renamed from "CRC Showcase" on 2026-11-05) | The module `crc_sdk.parametric` in the fork `marc272/crc-sdk` and the showcase notebook in the fork `marc272/crc-docs`, contributed by upstream PRs. Milestones R0 (the collaboration scan, done) to R4. Plan in §8, design in ADR 0005 | The forks (R-10, Human), ADR 0005 (R-12, D10), the golden fixtures from the core (R-13) |
| **CLIMADA Contribution** (second priority) | A parametric insurance module motivated by the thesis, and its tutorial. The module is hazard-agnostic, carries both ideas (the objective and the calibration scope) and targets `climada_petals` (location to be agreed with maintainers). The prototype in this repository (MAR-168) takes a slot when CRC has no ready agent work | Parity gate, F-10, F-12, maintainer alignment |
| **Foundation** (paused) | New repository, core library, data contract, CLIMADA hazard pipeline, thesis parity, core v1 features (F5), public-ready repository (F6, §7). The core is the CRC module's reference implementation and test oracle | — |
| **Website & Blog** (paused) | v1: explorers and posts 1–2. v2: robustness explorer, post 3, relaunch with the preprint | v1: F-09, F-10, the F6 repository clean-up. v2: Paper |
| **Paper** (paused) | Scientific basis, long track: checkpoint C1, portfolio and scenarios, robust design, manuscript | Core v1 features |

Linear (team MAR), with the issues each project started with (later issues are in Linear):
- *Program hub*: no issues; description plus status updates.
- *CRC Contribution: parametric insurance module*: MAR-41 to MAR-46, MAR-167, MAR-242 to MAR-250. MAR-41 to MAR-46 were the old R-01 to R-05 and were reused on 2026-11-05.
- *CLIMADA Contribution*: MAR-47 to MAR-51.
- *Foundation: core rework*: MAR-5 to MAR-27, MAR-61, MAR-63 to MAR-73.
- *Website & Blog*: MAR-52 to MAR-60, MAR-74.
- *Paper: tail-risk portfolio design*: MAR-28 to MAR-40, MAR-62.

Labels: Human, Gate, Decision, Spike, Research, Chore (plus Linear's Feature). Cross-project dependencies are Linear "blocked by" relations.

**Stream rules** (Program hub, 2026-11-05):

- Ready CRC Contribution issues get worker slots first, in milestone order: R1 → R2 → R3 → R4.
- CLIMADA Contribution issues get a slot only when CRC has no ready agent work.
- Issues in paused projects (Foundation, Website & Blog, Paper) are not dispatched, even in Todo, until Marc resumes a project.
- The CRC module never imports `parametric_insurance_design`. Parity with the core is checked through golden fixtures (MAR-245).
- Nothing new goes into crc-sdk's base install. The solver is an optional extra, chosen in ADR 0005.
- The CLIMADA stream stays CRC-free.
- Work in the forks follows `AGENTS.md`, "Working in the CRC forks", together with each fork's own `AGENTS.md`.

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
│   ├── viz/             # parametric-insurance-design-viz: matplotlib figures, reading the result store and the runs' content-hashed input EventSets; never solving or re-optimising (C6)
│   ├── crc/             # parametric-insurance-design-crc: dormant AGPL adapter skeleton (py>=3.12); the CRC data path lives in crc_sdk.parametric
│   └── climada/         # parametric-insurance-design-climada: tracks → CLIMADA → EventSet (own pixi env, NOT a uv member)
│       └── src/petals_parametric/  # prototype of a climada_petals parametric module (MAR-168); imports none of this repository's packages
├── examples/            # runnable scripts on the public API (core and viz only), smoke-tested in CI; BSD (ADR 0004 Q6)
├── research/            # paper: configs, run scripts, figure scripts, manuscript
│   └── configs/         # research run configs; climada/ holds the research-only CLIMADA build configs (ADR 0004 Q5)
├── showcase/crc/        # the record of the CRC collaboration scan and meeting brief; the notebook is built in the crc-docs fork
├── site/                # static website, reading exported bundles
├── parity/              # thesis golden data and parity tests
└── docs/                # SPEC.md, ADRs, methodology notes
    ├── concepts/        # the two core ideas and their combination: the tail-risk objective, portfolio calibration and both together (ADR 0004 Q4)
    └── reviews/         # design reviews (ADR 0004 Q4)
```

### 4.1 Environments

- **uv workspace** (core, viz, crc, research tooling). One lockfile. Core supports Python 3.11–3.13, numpy ≥1.26 and pandas ≥2.1 so that the CLIMADA env can import it.
- **pixi env** for `packages/climada`: CLIMADA from conda-forge, with core installed as an editable path dependency. Not in the uv lock, because CLIMADA's numpy pin would clash with CRC's pandas ≥3 requirement.
- Streams talk to each other only through **EventSet Parquet files** (§5). Example: the CLIMADA pipeline writes an EventSet, and the uv-side research code reads it.
- The CRC module lives in the crc-sdk fork, in crc-sdk's own environment. It reaches the core only through golden fixtures (MAR-245), never through an import.

### 4.2 Core modules (`packages/core/src/parametric_insurance_design/`)

The adapter and viz distributions import as `parametric_insurance_design_viz`, `parametric_insurance_design_crc` and `parametric_insurance_design_climada`.

| Module | Responsibility |
|---|---|
| `eventset.py` | `EventSet`: dense index and loss matrices, events, locations, metadata. Parquet I/O. Validation |
| `index.py` | Index definitions: point intensity, value-weighted cluster index. Precomputed custom indices (e.g. cat-in-a-circle from the CLIMADA adapter) |
| `payout.py` | `PayoutStructure` → basis matrix. `StepPayout` (breakpoints, monotone, capped) is implemented. Piecewise-linear is designed for but not built |
| `scopes.py` | `Individual`, `Portfolio`, `Cluster(strategy)`. Map assets to payout entities and set the aggregation level of the objective. `Cluster` calibrates its clusters jointly by default (`joint=True`, the thesis); `Cluster(joint=False)` solves one design problem per cluster (`problem_id` `cluster:C<k>`), which separates the cluster index from joint calibration (MAR-180) |
| `clustering.py` | Port of the thesis feature-plus-Ward clustering, as a pluggable strategy |
| `objectives.py` | `MSE`, `ExpectedUncovered`, `WeightedCVaR(alpha, beta)` (Rockafellar–Uryasev) |
| `pricing.py` | `PurePremium`, `CostOfCapitalLoad(rate, q)`. Std-dev load is optional (SOCP) |
| `problem.py` | Assembles a cvxpy problem from scope × payout × objective × pricing × constraints |
| `solve.py` | Solver policy (Clarabel → HiGHS/SCS fallback), `SolveResult`, typed `SolveError` |
| `workflow.py` | `design()`: builds every problem of a scope and solves each, in one call (`problem.build_problems`, then `solve.solve`; ADR 0004 Q2, ADR 0002 §1 amendment MAR-184) |
| `evaluate.py` | KPIs: VaR/CVaR(U), E[U], RMSE, E[π]/E[L], correlation, exceedance curves on an event or annual basis |
| `riskmeasures.py` | `var_cvar` and the lower quantile of a discrete distribution, shared by `pricing.py` and `evaluate.py` (MAR-143) |
| `bootstrap.py` | Block-bootstrap CIs over years, filling the `kpis.ci_*` columns (MAR-23) |
| `splits.py` | Year-block train/test and k-fold. Copies of an event (noise/vulnerability draws) never cross folds |
| `robust.py` | Scenario-robust (R1) and distributionally robust (R2) wrappers (§6.5) |
| `experiment/` | Subpackage (ADR 0002 §8): `config.py` config schema, `runner.py` run executor and content-hashed caching, `store.py` result store, `sweeps.py` one-factor-at-a-time sweeps, `kfold.py` pooled k-fold out-of-sample KPIs at the portfolio level, computed on demand from the store (MAR-151) |
| `cli.py` | The `parametric-insurance-design` command: `run`, `sweep`, `figures` (MAR-110, MAR-112) and `export-site` (MAR-200). `figures` and `export-site` import viz lazily; the core never depends on it |
| `noise.py` | Thesis noise layer (homo/heteroscedastic lognormal), bit-identical port for parity. The thesis baseline of §6.3, supported. Off the top level: imported by its full name, `parametric_insurance_design.noise` (ADR 0004 Q2, ADR 0002 §10) |
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
  | `packages/crc` | **AGPL-3.0-or-later** | Written to import `crc-sdk` / `crc-framework`, which are AGPL-3.0-or-later on PyPI. Dormant since 2026-11-05: the CRC data path lives in `crc_sdk.parametric`. Revisit if the owner's CRC agreement grants other terms for the SDK |

  The CRC module `crc_sdk.parametric` isn't in this repository. It is built in the crc-sdk fork and takes crc-sdk's AGPL-3.0-or-later (D3, D9). The notebook's terms are Marc's (2026-11-05).

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

In memory, an EventSet is a dense `(n_rows, n_locations)` index matrix and loss matrix, plus aligned event metadata. A threshold filter may drop rows only for speed. That is true only for a step payout with `below_attachment="zero"` and a filter at or below the attachment, where a row below the attachment pays nothing whether it is kept or dropped: under the default `"first_bin"`, a kept row below the attachment pays θ_{j,0} and a dropped one pays nothing, so the design and its premium depend on the filter (module docstring of [`payout.py`](../packages/core/src/parametric_insurance_design/payout.py); MAR-170). Rates are **never** rescaled, so dropped rows count as zero-loss mass.

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
Using the core v1 features (§6.1–6.4), answer one question per story (§1):
- **RQ1 (tail):** *does the weighted-CVaR design still lower tail basis risk out of sample, under realistic basis risk and loaded pricing, compared with MSE and E[U] designs, for each scope?*
- **RQ2 (portfolio):** *at the same budget, does joint calibration (portfolio or cluster scope) lower the owner's shortfall out of sample, against individual calibration, under each objective (MSE, E[U], weighted CVaR)?* This is a scope comparison at the same budget, per objective.

The answer:
- fixes the paper's narrative (D4 venue, D6 R2 inclusion);
- decides which general claims the external outputs may make (publication rule, §1).

It does **not** gate the other outputs. The CRC module and notebook, the CLIMADA module, website v1 and posts 1–2 present the method and the tool.

**Outcome** (decided 2026-11-01, MAR-29; `research/checkpoints/C1.md`): the narratives are "when does it pay?" for both stories, "when does tail optimisation pay?" (RQ1) and "when does joint calibration pay?" (RQ2, whose paper claim waits for the Florida rerun, MAR-152 item 4); the combination analysis is MAR-182 (`research/notes/c1-combination.md`).

### 6.5 Robust design under uncertainty (the extension)
Uncertainty is represented as scenario EventSets S_0 (reference) … S_K. Each is one of:
- (i) a second hazard catalogue: none (D7 revisited 2026-10-31, MAR-62: STORM is unavailable). R1 covers vulnerability and climate scenarios only, and hazard-model uncertainty is a stated limitation;
- (ii) a vulnerability parameter draw (§6.3);
- (iii) a climate scenario: CLIMADA's Knutson/Jewson TC climate scaling, 2050, SSP2-4.5 and SSP5-8.5;
- (iv) optional: a bootstrap resample of years.

- **R1 scenario-robust (primary):** min_θ max_k F_k(θ), with the premium priced on S_0. LP via epigraph: t ≥ F_k(θ) for all k, each F_k with its own Rockafellar–Uryasev auxiliaries.
- **R2 distributionally robust (secondary; D6, decided at C1: yes, conditionally: MAR-35 starts with a relevance check):** worst case of the objective over year weights q in an ambiguity ball around the empirical weights (total-variation → LP, χ² → SOCP). Radius ρ is swept.
- **Evaluation:**
  - leave-one-scenario-out: design on S_0, or robustly on the other scenarios, then test on the held-out S_k;
  - **price of robustness**: premium or E[U] cost versus tail basis risk saved under misspecification.
- **Acceptance:**
  - R1 is implemented and tested (with K = 1 it matches the nominal solution);
  - results cover uncertainty sources (ii) and (iii) (no (i): D7 revisited);
  - a price-of-robustness figure exists for each scope.

### 6.6 Portfolio (D2, decided 2026-10-27 after spike P-05)
- **Requirements:**
  - single risk owner;
  - 25–200 assets inside the IRIS North Atlantic domain (US Gulf/East coast, Caribbean, Central America);
  - defensible values, or a documented value proxy.
- **Candidates:**
  - (a) a real company's assets from the **VELO/CDT database**: real coordinates and asset types; values need a proxy; may be anonymised in the paper;
  - (b) CLIMADA LitPop municipal/sovereign portfolio (fully open, which the CLIMADA tutorial needs anyway);
  - (c) Overture candidate locations.
- **Decision (D2, MAR-30, 2026-10-27; note in `research/notes/d2-paper-portfolio.md`):**
  - **Source:** (b) LitPop now; revisit (a) VELO/CDT after MAR-41.
  - **Region and owner:** Florida's 67 counties, with the State of Florida as the single risk owner. Each county's value is the sum of the cells of the pinned CLIMADA data-API file `LitPop_150arcsec_USA` v3 (uuid and MD5 in the note).
  - **Single risk owner:** a government whose loss is the modelled LitPop asset loss in its territory, stated as a documented proxy.
  - **Index for an aggregated unit:** wind at the value-weighted centroid, plus cat-in-a-circle around it. Both are already in §6.3.
  - **Publication constraints:** CC BY 4.0 attribution on every output, no anonymisation, and the derived EventSet recorded as `CC-BY-4.0`.
  - **K-04 tutorial:** reuses the paper portfolio (the same data).
  - **Fallback:** Puerto Rico's 78 municipalities.
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

**F6, public-ready repository** (Foundation milestone, added 2026-10-31): the design review (MAR-161), the structure decision (D8, MAR-162; ADR 0004), concept docs (MAR-163), READMEs (MAR-164) and examples (MAR-165). The website, the posts and the CLIMADA module link to the repository, so F6 comes before they go out.

---

## 8. Other projects: milestones

**CRC Contribution: parametric insurance module** (the main priority, Marc, 2026-11-05)

The module's design is ADR 0005 (R-12, D10, pending Marc's approval); this list is the plan. The module is built in the forks (D9, §11), under `AGENTS.md`, "Working in the CRC forks". R0, the collaboration scan (MAR-167), is done, and this plan replaces its candidate plan R-01 to R-05. MAR-41 to MAR-46 were the old R-01 to R-05 and were reused on 2026-11-05.

- **R1, setup and module design.** Everything in the forks waits on R-10 and on Marc's approval of R-12.
  - R-10 Fork crc-sdk and crc-docs to marc272, create the `parametric` branches and enable Actions (Human, MAR-242)
  - R-11 The program rules and docs for the fork workflow (MAR-243)
  - R-12 The module design: ADR 0005 for `crc_sdk.parametric` (D10, MAR-244; Marc approves)
  - R-13 Golden fixtures from the core for the module's tests (MAR-245)
- **R2, Phase 1: the module in crc-sdk.** One asset, one hazard; the dimensions for Phase 2 are reserved. In order:
  - R-14 Covers, payout functions and their parameters (MAR-246)
  - R-15 Outcome samples: index and loss per year from CRC data (MAR-43)
  - R-17 Evaluation and comparison: coverage, tail coverage and basis-risk metrics (MAR-247)
  - R-16 Design: optimise a cover's free parameters for an optimisation goal (MAR-248)
  - R-18 The end-to-end workflow from assets, hazard and impact to designed and evaluated covers, with docs (MAR-42)
- **R3, Phase 1: the notebook and the upstream PRs.**
  - R-19 The showcase notebook in crc-docs: design, evaluate and compare covers (MAR-46)
  - R-20 Agree the contribution route with RiskThinking and open the upstream PRs to crc-sdk and crc-docs (Human, MAR-249)
- **R4, Phase 2: extensions**, each with its own notebook section and upstream PR:
  - R-21 The portfolio approach: design covers for one owner's assets jointly (MAR-45)
  - R-22 Multi-hazard covers: an index over two or more hazards (MAR-250)
  - R-23 Scenario analysis: evaluate and design covers under climate scenarios (MAR-44)
  - VELO assets for a real owner's book (MAR-41)

**Paper** (paused; the former P-01 to P-04 are now the Foundation core v1 features F-09 to F-12)

The paper reports both research questions and their combination (§1), each with its own evidence. RQ1 and RQ2 must each be answerable on its own: the portfolio story is not only a setting for the tail story. The combined design (a weighted-CVaR objective calibrated jointly across one owner's sites) is reported against each single-idea design, together with the interaction: does the tail gain depend on the scope, and does the joint gain depend on the objective? Venue (D4) and R2 (D6): §11.

- Positioning: literature review, from day one
- **C1 checkpoint:** the analysis on F-09 to F-12
- P-05 Portfolio spike and build (§6.6)
- P-06 Scenario EventSets (climate scenarios; no second hazard catalogue, D7 revisited, §6.5)
- P-07 Robust design R1, plus R2 (D6, decided at C1: yes, conditionally: MAR-35 starts with a relevance check) (§6.5)
- P-08 Experiments and figures
- P-09 Manuscript, arXiv preprint, Zenodo code release with DOI

Positioning: Steinmann et al. 2023 (CLIMADA parametric framework), Maier & Scherer 2025/2026 (expectile payouts, single risk), arXiv 2409.16599 (diversification).

**CLIMADA Contribution** (second priority; a parametric insurance module motivated by the thesis, carrying both ideas: the objective and the calibration scope. The prototype in this repository, MAR-168, continues when CRC has no ready agent work)
- K-01 Open a maintainer discussion (GitHub Discussion/issue) early, after F-03. Agree location (petals vs. core), solver dependency (cvxpy vs. scipy-HiGHS) and API style
- K-02 Module design ADR: works on `Hazard`, `Exposures`, `Impact` and `TCTracks`; index builders (centroid intensity, cat-in-a-circle); step payout; objectives; calibration scope (individual, cluster, portfolio); basis-risk metrics
- K-03 Implementation in a `climada_petals` fork: unit and integration tests, CLIMADA `.pylintrc`, AUTHORS entry. Starts after the parity gate, F-10 (annual basis), F-12 (cat-in-a-circle) and the accepted ADR. It does not wait for the paper
- K-04 Tutorial on open data only (LitPop plus synthetic tracks), showing both ideas: the tail objective and the calibration scope
- K-05 PR to `develop` and the review cycle
- Excludes: CRC, VELO, robust-design research code (unless the maintainers ask for it), paper experiments

**Website & Blog** (paused)

v1, which needs F-09 and F-10:
- W-01 Export bundle format: `parametric-insurance-design export-site` writes JSON and Arrow IPC slices, JSON for the manifest and small indexes and uncompressed Arrow IPC for the tables (Quarto OJS reads both; Parquet is not a documented OJS format). The manifest gives each file's size and SHA-256, the setup of every number and the bundle rules (infinities, NaN, size budget). Site skeleton in Quarto, deployed to GitHub Pages (D5, ADR 0003). Where the deployed bundle comes from: ADR 0003, "Where bundles come from in CI" (MAR-208: the Site workflow solves and exports `site/configs/explorer.yaml` itself)
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
- Multi-hazard parametric covers in the core and the paper. They are a Phase 2 feature of the CRC module (R-22, §8).
- Live in-browser solver on the website.
- Wasserstein DRO over the index/loss support (non-convex with step payouts).

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| Tail advantage disappears out of sample or under loaded pricing | C1 checkpoint. A negative or nuanced result is still publishable ("when does tail-optimisation pay?") |
| Joint-calibration advantage disappears out of sample (RQ2) | The in-sample joint gain may not carry over out of sample (C1 §6b), so the Florida rerun (MAR-152 item 4, MAR-202) is the real test. Neither the joint designs (MAR-100) nor the individual designs (MAR-198) are unique, so Florida's contrasts are read with their ranges across optimal designs (MAR-203). A conditions-based result ("when does joint calibration pay?", C1 §8) is still publishable. External outputs follow the RQ2 rule (§1), which the owner revisits after the Florida rerun |
| Parity can't be reached exactly (degenerate LPs, solver versions) | Compare objective values and KPIs rather than payout vectors. Document the gaps |
| CLIMADA maintainers decline the module or ask for big changes | Talk to them early (K-01). The paper and core don't depend on acceptance |
| VELO/CDT assets lack values, or publishing them is sensitive | Value proxy plus anonymisation. LitPop fallback |
| Environment clash (CLIMADA vs. CRC) | Separate envs. Parquet contract as the only interface |
| Scope creep | §9 is binding. New ideas go to the backlog unless C1 calls for them |
| Early outputs claim more than the evidence supports | Publication rule (§1, decided at C1): method and tool, setup stated; RQ1 only conditional, mechanism-based statements; RQ2 and anything involving joint calibration method only. The human approves every publication |
| Linear and the files drift apart | Linear is the source of truth for the what, when and status. The session start and end protocols (Program hub, `docs/ORCHESTRATION.md`) keep it current |

---

## 11. Decisions

Each decision's status and outcome is recorded on its **Linear issue**, which is canonical. Final technical outcomes also get an ADR.

| ID | Decision | Linear issue |
|---|---|---|
| D1 | Repository and package name: `parametric-insurance-design` (decided; ADR 0001) | MAR-5 |
| D2 | Paper portfolio source: CLIMADA LitPop (revisit VELO/CDT after MAR-41), Florida's 67 counties with the State of Florida as the single risk owner (a documented proxy); county values from the pinned `LitPop_150arcsec_USA` v3; CC BY 4.0 attribution, no anonymisation; fallback Puerto Rico's 78 municipalities (decided 2026-10-27; §6.6; note in `research/notes/d2-paper-portfolio.md`) | MAR-30 |
| D3 | Licences: BSD-3-Clause core/viz, GPL-3.0-or-later CLIMADA adapter, AGPL-3.0-or-later CRC adapter (decided; ADR 0001, §4.3). The CRC module takes crc-sdk's AGPL-3.0-or-later | MAR-5 |
| D4 | Target venue: *Natural Hazards and Earth System Sciences* (NHESS) (decided 2026-11-01 at checkpoint C1) | MAR-29 (C1) |
| D5 | Website stack: Quarto + OJS on GitHub Pages (decided 2026-10-25; ADR 0003) | MAR-52 |
| D6 | Include R2 (distributionally robust) in the paper: yes, conditionally (decided 2026-11-01 at checkpoint C1). MAR-35 starts with a short relevance check. If R2 doesn't add value or isn't tractable, the fallback is a short appendix or leaving it out, and the owner is told before that choice is made | MAR-29 (C1); MAR-35 |
| D7 | Second hazard catalogue: none (revisited 2026-10-31, because STORM is unavailable; R1 covers vulnerability and climate scenarios only, and hazard-model uncertainty is a stated limitation; §6.5). First decided 2026-10-25 as STORM, present climate v4, North Atlantic, CC0 (note in `research/notes/d7-second-hazard-catalogue.md`) | MAR-62 |
| D8 | Repository structure for external presentation: as recommended for all seven questions (decided 2026-11-01; ADR 0004). The agent files stay at the root, signposted in the README (1A); the stories' components and `pid.design` at the top level, `robust` and `noise` off it (2B + 2D); flat modules (3A); a docs index, `docs/concepts/` and `docs/reviews/`, with quartodoc in the Quarto site (4A + R1); the radius configs move to `research/configs/climada/`, the STORM configs are removed and the loader kept (5b); `examples/` at the root, smoke-tested in CI (6A); 0.1.0 for core and viz, a root CHANGELOG at release time, PyPI at website v1, published by the owner (7a, P1) | MAR-162 |
| D9 | CRC contribution home and build location (decided 2026-11-05 by Marc): the module goes in crc-sdk, as `crc_sdk.parametric`, with the notebook in crc-docs. Both are built in marc272 forks (`marc272/crc-sdk` and `marc272/crc-docs`, integration branch `parametric`), with agent pushes and orchestrator merges into `parametric` allowed. Each phase ends in an upstream PR, which is Marc's (MAR-249). Everything else is paused. This repository holds the reference implementation and test oracle (the core, and golden fixtures for the module, MAR-245), the design record (ADR 0005), the CLIMADA prototype and the paused tracks | MAR-242 |
| D10 | CRC module design: ADR 0005, prepared by agents. Pending Marc's approval | MAR-244 |

---

## 12. Delivery workflow (orchestrated agents)

The build is delegated to worker agents coordinated by an orchestrator agent, with the owner making all decisions.

- **Linear is the ground truth** for goals, priorities, plan, decisions and status. Every agent starts at the Program hub: its description and its latest status update. Before ending a session, the agent leaves Linear true.
- **Entry point:** the repo's [`CLAUDE.md`](../CLAUDE.md), which loads `AGENTS.md` and points the orchestrator to the runbook. The workspace `CLAUDE.md` outside the repo was the entry point until the repo existed; it now points here.
- **Scheduling across streams** (Program hub, 2026-11-05; details in the runbook):
  - CRC Contribution first, in milestone order R1 → R4;
  - CLIMADA Contribution only when CRC has no ready agent work;
  - no dispatches from the paused projects (Foundation, Website & Blog, Paper).
- **Three repositories:** this one, and the forks `marc272/crc-sdk` and `marc272/crc-docs` (D9). Workers in the forks branch from `parametric` and open PRs into it; the orchestrator merges them. Agents never act on RiskThinking's repositories.

- **Worker agreement:** [`AGENTS.md`](../AGENTS.md). Covers sources of truth, one issue = one PR, file ownership, the rules for working in the CRC forks, definition of done, escalation, and what agents never do.
- **Orchestrator runbook:** [`docs/ORCHESTRATION.md`](ORCHESTRATION.md). Covers status semantics (Todo = all blockers Done), the dispatch/review/merge loop across the three repositories, WIP limits, gates, the human queue and the plan.
- Both were drafted in the workspace's `repo-seed/` folder and live in this repository since the bootstrap (MAR-6), together with `CLAUDE.md` (`@AGENTS.md`).
- Linear labels:
  - **Human:** never completed by agents; only its "Agent may prepare" part may be delegated;
  - **Gate:** human sign-off unblocks downstream work;
  - **Decision:** a D1–D10 item, always also Human.
- **Contract-first:** MAR-61 fixes the core interfaces and a module ownership map (ADR 0002) before parallel implementation starts.
- Issues with sub-issues (MAR-17, MAR-18, MAR-19) are containers and are never dispatched themselves.
