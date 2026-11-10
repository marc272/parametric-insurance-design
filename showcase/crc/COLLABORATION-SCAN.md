# R-00 collaboration scan: Climate Risk Commons and RiskThinking public repositories

**Status: observations and options for the owner, Marc Prinzing. The choice is his.** An agent prepared this file on 2026-11-01 from public sources only: GitHub repositories, PyPI metadata and public data-release files. It made no contact with RiskThinking, used no credentials and called no keyed API. It quotes no more than a line of their text, always with a link.

- Issue: MAR-167 (R-00). The one-page brief for the meeting is [`MEETING-BRIEF.md`](MEETING-BRIEF.md).
- **Builds on** the R-01 inventory (MAR-41, PR [#12](https://github.com/marc272/parametric-insurance-design/pull/12), `showcase/crc/INVENTORY.md`, not yet merged). That file has the CRC Open hazard table, coverage of the North Atlantic domain, the VELO/CDT asset schema, the value-proxy options V1–V5 and a query plan. This scan doesn't repeat them; it cites them as "INVENTORY §n".
- Spec: `docs/SPEC.md` §5 (the `EventSet` contract), §6.6 (portfolio) and §8 (CRC Showcase). Concepts: `docs/concepts/` (the tail objective, portfolio calibration and their combination). Licences: ADR 0001.

Contents:

1. [Summary](#1-summary)
2. [What exists](#2-what-exists)
3. [Fit with the two core ideas](#3-fit-with-the-two-core-ideas)
4. [Collaboration options](#4-collaboration-options)
5. [Recommended approach (agent)](#5-recommended-approach-agent)
6. [Questions for RiskThinking](#6-questions-for-riskthinking)
7. [Unverified points and follow-ups](#7-unverified-points-and-follow-ups)
8. [Sources](#8-sources)

---

## 1. Summary

- **CRC is hazard distributions plus an impact and risk toolkit, not an event model.** CRC Open serves fitted per-cell marginal curves for 63 hazards (SSP5-8.5, H3 r5 or r7, CC BY-NC 4.0; INVENTORY §1). `crc-framework` adds damage functions for cyclone, flood and rainfall, and VaR/CVaR over **independent** binary outcomes. Nothing in the six repositories builds events, simulated years or dependence between sites. RiskThinking's own docs list "dependence calibration" as absent ([capability matrix](https://github.com/RiskThinking/crc-docs/blob/10d4ea8d01c16ebe3846fecddb391ab32b8be030/ai-playbooks/docs/capability-matrix.md)).
- **There is no parametric insurance anywhere in their public code.** A search of all six repositories for payout, trigger, basis risk and parametric insurance finds nothing relevant (§2.5). The nearest piece is the `crc-model-flood-insurance-loss` skill. It computes damage ratios and rules out prices and coverage terms.
- **Their docs ask for the kind of piece we have.**
  - The gap backlog asks for "high-level decision playbooks", an insurance loss workflow among them.
  - It also asks for multi-hazard portfolio work with "joint modelling".
  - The product strategy names property insurance as the second demo domain.
- **Fit with our library.** The `EventSet` needs an index and a loss for every event (or year) and location.
  - **One site, or sites designed one by one** (the individual scope, and the tail objective, RQ1): feasible on CRC Open alone. We sample annual outcomes from a site's marginal, take the loss from a CRC damage function, and add a stated basis-risk model.
  - **Joint calibration and the combination** (RQ2 and RQ1 × RQ2): need a joint distribution across sites, which CRC doesn't provide. They also need relative asset values, and VELO's `asset_value` is 0 in every public example (INVENTORY §2.4).
- **Contribution route.** None of the six repositories has a contribution guide, PR template or CLA. `crc-docs`, where the skills, notebooks and pipelines live, has **no licence file**. `crc-sdk` and `crc-framework-rs` credit contributors through All Contributors (code, review and research).
- **Recommendation (agent, §5).** Build in our repository and ship in their format.
  - Phase 1 is a **general parametric layer** on CRC Open: index, trigger, step payout and basis-risk metrics. Its design step is our optimiser, with the objective as a setting, so the tail objective is available from day one. It covers one site, or many sites designed one by one, and is packaged as a CRC-style skill, notebook and pipeline.
  - Phase 2 adds joint calibration and the combination on one owner's sites, once a dependence source and an asset book are agreed.
  - The main risk is dependence: on CRC data, any joint-calibration result would rest on a dependence model that we impose.

---

## 2. What exists

### 2.1 Repositories

All public repositories of the GitHub organisation [`RiskThinking`](https://github.com/RiskThinking), read on 2026-11-01. "Last activity" is the head commit of the default branch.

| Repository | What it is | Licence | Language, Python | Last activity (commit read) | Relevance |
|---|---|---|---|---|---|
| [`crc-sdk`](https://github.com/RiskThinking/crc-sdk) | The Python SDK for CRC. It covers source access (CRC Open, JRC flood, JRC/EDO drought, ERA5, CMIP6, NOAA ISD/GHCNh, ECCC IDF, OS-Climate, bring-your-own Zarr/GeoTIFF/tables) and canonical hazard Parquet. Its workflows include `HazardDataset.for_assets(...).return_periods(...).impact(...)`, which evaluates a portfolio at return periods, plus H3 geometry and PMTiles | AGPL-3.0-or-later (`pyproject.toml`; GitHub shows `NOASSERTION` because the LICENSE file starts with a preamble) | Python ≥ 3.11. CI runs 3.11–3.15; 3.11–3.13 gate releases | `532cf448a413431a5fd50ca7be0eb129674c3feb`, 2026-10-30 ("validate releases"). PyPI 0.9.1, 2026-10-30 | **High.** The adapter's data path (MAR-42/43). Its portfolio and impact workflow is the natural place to attach a payout step |
| [`crc-framework-rs`](https://github.com/RiskThinking/crc-framework-rs) | A Rust core with Python (`crc-framework`) and JS/WASM bindings. It holds the distributions and fitting, impact functions (linear, sigmoid, piecewise, and a registry by risk factor and context), impact contracts with a definition hash, microscores, and VaR/CVaR with attribution over binary outcomes | AGPL-3.0-or-later | Rust ≥ 1.85, Python ≥ 3.11 | `6edee70f0e3ea754aa2f3ba66c57adb0f2f433e9`, 2026-10-27 (0.5.3). PyPI 0.5.3, 2026-10-27 | **High.** Damage functions are a ready loss model, and CVaR is a shared vocabulary. Its README says application workflows belong in packages built on the framework |
| [`crc-docs`](https://github.com/RiskThinking/crc-docs) | The "Climate Risk Commons" front door. It holds 8 AI skills (`.agents/skills/*/SKILL.md`), 14 notebooks (Colab-ready, outputs saved), 12 headless pipelines, fixtures, and playbook docs (capability matrix, gap backlog, product strategy) | **None**: no LICENSE file; GitHub reports no licence | Python ≥ 3.12; `crc-sdk[...]>=0.9.0,<1` | `10d4ea8d01c16ebe3846fecddb391ab32b8be030`, 2026-10-28. The local read-only checkout `../crc-docs` is at `f05a8569`, 2026-10-23, two commits behind | **High.** The format a showcase or contribution would follow (§2.4) |
| [`velo-sdk`](https://github.com/RiskThinking/velo-sdk) | A Python client for the keyed VELO API: companies, assets, market indexes, climate scores | Apache-2.0 | Python ≥ 3.11 | `ae1aebec31cd7e831a8a53c594bfa4f426c2b3d6`, 2026-02-26 (0.0.20). Unchanged since INVENTORY §2 | **Medium.** Source of one owner's asset book (INVENTORY §2). Needs a key, which only the owner holds |
| [`cdt-express-mcp`](https://github.com/RiskThinking/cdt-express-mcp) | An MCP server for CDT Express (remote OAuth or local key), with read-only tools for assets, companies, markets and location climate metrics | MIT | TypeScript | `9795061c4c80bbd661ccc00a125fba072fa04d92`, 2026-10-27 (v0.7.0: simpler setup, privacy-policy link). INVENTORY §2 read v0.6.0 | **Low–medium.** An access route to VELO data, not a data source of its own (INVENTORY §2.1, §2.9) |
| [`cdt-express-notebooks`](https://github.com/RiskThinking/cdt-express-notebooks) | 9 example notebooks for CDT Express, with credit rules | Apache-2.0 | Python | `07de3194b0a7eeb1ad2bf1cfefad671e893bbe4c`, 2025-06-18 | **Low.** Schema evidence only (INVENTORY §2.3) |
| `DELPHI`, `RTai_4CastNet`, `argminmax`, `corona_tscs`, `work-samples` | Older or unrelated work: epidemiology, a FourCastNet fork, a Rust utility, COVID data, hiring samples | various | — | last push 2020–2025 | None |

### 2.2 Data products

- **CRC Open** (public, no key): release `ssp585-global-2026-10-20-v1`, still the only full release on 2026-11-01. `crc-sdk` 0.9.1 names only it and the docs fixture `ssp585-fixture-2026-10-08-v2`, and its `_SUCCESS` marker still answers. It has 63 hazards, SSP5-8.5 only, no historical baseline, and H3 r5 (about 253 km²) or r7 (about 5 km²) for flood. The licence is CC BY-NC 4.0, with attribution "Riskthinking.AI bias-corrected climate distributions". Details are in INVENTORY §1. Points that matter for parametric design:
  - `rx1day`, `rx5day` and the wind maxima declare `probability_semantics: annual_value_distribution`: the distribution of an annual value across years and ensemble members. That is the semantics an annual-basis EventSet needs.
  - `cyclone` (m/s, r5) is pooled and scenario-independent. Its probability semantics are **not declared**, and neither is the wind definition (INVENTORY §1.4). The same holds for `rflood`, `cflood` and `inundation`.
  - The SDK's [ADR 0003](https://github.com/RiskThinking/crc-sdk/blob/532cf448a413431a5fd50ca7be0eb129674c3feb/docs/adr/0003-probability-semantics.md) ("Proposed") defines the semantics vocabulary and the T↔p convention. An absent value means `unspecified`.
- **Open sources through `crc-sdk`.** JRC EFAS/GloFAS flood maps and JRC/EDO drought (CC BY 4.0), ERA5 baselines, CMIP6 projections, NOAA ISD/GHCNh station extremes and ECCC IDF curves can all be brought into the same canonical Parquet. Licences are per source, in the SDK's [licence policy](https://github.com/RiskThinking/crc-sdk/blob/532cf448a413431a5fd50ca7be0eb129674c3feb/docs/licence-policy.md). That policy lists STORM cyclone winds and IBTrACS as unverified candidates; it calls IBTrACS an "event-data utility only".
- **VELO/CDT** (keyed, owner's licence): the same 63 risk factors as location marginals, plus more pathways. It also serves asset and company data: coordinates, type, one owning company, an H3 r7 cell, and `asset_value`, which is 0 in every public example. No public data terms were found. Details are in INVENTORY §2.

### 2.3 SDKs and APIs

| Package | Version (2026-11-01) | Licence | Python | Key? |
|---|---|---|---|---|
| `crc-sdk` | 0.9.1 (0.9.0 on 2026-10-27) | AGPL-3.0-or-later | ≥ 3.11 | No, for CRC Open and the open sources |
| `crc-framework` (PyPI), `@climateriskcommons/crc-framework` (npm) | 0.5.3 | AGPL-3.0-or-later | ≥ 3.11 | No |
| `velo-sdk` | 0.0.20 | Apache-2.0 | ≥ 3.11 | Yes |
| CDT Express MCP | 0.7.0 | MIT | — | Yes (OAuth or key) |

Both CRC packages release often: `crc-sdk` had 5 releases between 2026-10-21 and 2026-10-30. An adapter should pin versions and test against the minimum it supports, as `crc-sdk` does with `crc-framework`.

Our adapter `packages/crc` declares Python ≥ 3.12, which matches `crc-docs` (≥ 3.12) but is stricter than `crc-sdk` (≥ 3.11).

### 2.4 Pipelines, notebooks and the skill format

`crc-docs` pairs every problem with a skill, a notebook and a headless pipeline (the README's "Choose a problem" table).

- **Relevant notebooks:**
  - `crc_open_hazards`: CRC Open screening;
  - `portfolio_impact`: event-aligned impacts;
  - `portfolio_risk_metrics`: binary outcomes and VaR/CVaR;
  - `multi_scenario_portfolio`: local tail stresses;
  - `hurdle_fit_primer`.
- **Their pipelines:** `crc_open_pipeline.py`, `portfolio_impact_pipeline.py`, `portfolio_risk_pipeline.py`, `asset_portfolio_pipeline.py` and others. They take CSV or Parquet assets and write Parquet, CSV, GeoJSON and an HTML report with a manifest.
- **Skill layout:**
  - `SKILL.md` with a front-matter `name` and `description`;
  - a "refresh from the canonical source" bootstrap that pins the `crc-docs` commit;
  - guided intake;
  - a demo bootstrap on illustrative inputs;
  - the workflow;
  - required output and a deliverable bundle (results table, map, charts, manifest);
  - `references/playbook.md`, `scripts/*.py` and `agents/openai.yaml`.
- **Conventions a contribution would follow:**
  - no silent asset drops;
  - no silent return-period extrapolation;
  - no historical/future substitution;
  - no thresholds without an owner-approved policy;
  - provenance on every result (gap backlog, "Quality gates for all demos").
- **CI:** `validate-skills.yml` checks the skill tree, `CLAUDE.md` = `@AGENTS.md` and `.mcp.json`. `tests/` runs the notebooks and pipelines.

These match our own rules: no silent failures, a provenance manifest, and coverage exceptions kept visible (MAR-46).

### 2.5 Financial, insurance and risk-transfer components

| Component | Where | What it does | Limits stated by RiskThinking or seen in code |
|---|---|---|---|
| Damage functions (impact registry) | `crc-framework` `impacts.for_factor(...)`; registry in `crates/core/src/impact/registry.rs` | Damage ratio from hazard. There are entries for `cyclone` and `wind_max_daily_max` (wind tables with per-country parameters), `rflood`, `cflood`, `inundation` (flood), `rx1day`, `frost_days` and `daily_freezethaw_cycles`. Context: continent, country, building type, historic mean | "Registry availability does not establish applicability to an insured exposure" (capability matrix). Calibration sources are not documented in the files read |
| Explicit curves and contracts | `crc-framework` `PiecewiseLinearImpact`, `ImpactExpression.tabulated`, `ImpactCalibration`; SHA-256 `definition_hash` | Reproducible user-supplied depth-damage curves | — |
| Event-aligned portfolio impact | `crc-sdk` `PortfolioEvaluation.impact(...)` | `value_rp100 = impact(hazard_rp100)` per asset | Per return period: it isn't a loss distribution, and assets are evaluated one at a time |
| Microscores and risk aggregation | `crc-framework` `generate_microscores`, `BinaryOutcome`, `compute_spanning_set`, `compute_risk` | VaR/CVaR and factor attribution over 2ⁿ branches of binary outcomes | It assumes independent outcomes, and the capability matrix calls it "not a full joint continuous-loss model" |
| Flood insurance loss skill | `crc-docs/.agents/skills/crc-model-flood-insurance-loss` | Damage ratios by return period, and a currency loss when values are supplied | It rules out premium, price, reserve and capital, and coverage terms, deductibles and limits |
| VELO insurability triage | `velo-triage-portfolio-insurability` skill; VELO asset scores | `cvar_95` damage as % of asset value. Platform labels: `cvar_95 >= 0.35` is "uninsurable" | Platform labels, not underwriting rules (capability matrix) |
| **Absent** | all six repositories | No parametric insurance, payout, trigger, basis risk, event set, simulated years, copula or cross-site dependence. Grep evidence is in §8 | — |

So the loss side exists (damage ratio × value), and so does the tail-metric vocabulary (CVaR). What's missing is the joint distribution and any risk-transfer design.

### 2.6 How they accept contributions and showcases

- **No contribution guide, PR template, issue template or CLA** in any of the six repositories.
- **Credit:** `crc-sdk` and `crc-framework-rs` keep an All Contributors roster, with types code, review and research, and say they credit contributions "on and off GitHub". The `crc-sdk` roster lists seven people.
- **`crc-docs` has no licence.** By default that means all rights reserved. Reusing their skills or notebooks, or contributing to them, needs terms from RiskThinking.
- **Showcase framing.** The [product strategy](https://github.com/RiskThinking/crc-docs/blob/10d4ea8d01c16ebe3846fecddb391ab32b8be030/ai-playbooks/docs/product-strategy.md) gives a six-step demo narrative: frame the problem, CRC baseline, provenance, VELO twin, reconcile, decision memo. It ranks property insurance as the "strong second demo" and keeps pricing and capital claims out of scope without actuarial calibration.
- **Open work they list** ([gap backlog](https://github.com/RiskThinking/crc-docs/blob/10d4ea8d01c16ebe3846fecddb391ab32b8be030/ai-playbooks/docs/gap-backlog.md), reviewed 2026-09-15):
  - P0, multi-hazard portfolio orchestration: "joint modelling" is left to the caller;
  - P1, "high-level decision playbooks", an insurance loss module among them;
  - P1, vulnerability packs;
  - P2, a calibration and backtesting harness.
  - A parametric design step answers the first two directly.

---

## 3. Fit with the two core ideas

### 3.1 What our library needs, and what CRC gives

The core designs on an `EventSet` (SPEC §5): rows = events (or simulated years, each row with a rate), columns = locations, with an **index** and a **loss** per row and location, plus asset values.

| EventSet input | From CRC / VELO | Gap and how to close it |
|---|---|---|
| Rows (events or years) | None. CRC Open curves are per-cell marginals | Sample *N* years per site from the marginal (inverse CDF). This is natural for `annual_value_distribution` hazards and fits our annual basis (SPEC §6.2). For `cyclone` it rests on an assumed convention until the semantics are confirmed |
| Index x per row and site | The CRC hazard value at the site's cell | Ready. Sites in one r5 cell get identical marginals: the 9 thesis Miami assets fall in 5 r5 cells (INVENTORY §1.5) |
| Loss L per row and site | A `crc-framework` damage function × value | **Basis risk must be modelled.** If the loss is a deterministic function of the same hazard at the same cell, index and loss are comonotone, and a step payout can track the loss almost exactly. A stated basis-risk model is needed: vulnerability draws as in SPEC §6.3 (`draw_id`); index at a coarser or reference cell; or index and loss from different hazards. The last two need dependence |
| Dependence across sites | None. The capability matrix lists no dependence calibration, and `crc-framework` CVaR assumes independent outcomes | Needed only for joint scopes and for owner-level KPIs. Options: (i) the IRIS empirical copula (MAR-45; cyclone, North Atlantic only); (ii) an assumed copula as a stated sensitivity; (iii) co-simulated fields or the per-year samples behind the pooled CDFs, **if RiskThinking has them** (question Q1) |
| Values | VELO `asset_value`, 0 in every public example; proxies V1–V5 (INVENTORY §2.4) | A single site can work in damage-ratio units (value = 1). Joint calibration needs relative values |
| One owner | VELO `company_id` (one owner per asset), or a user-supplied asset book | Ready for user-supplied assets. VELO needs a key and data terms |

### 3.2 Where each idea plugs in

| | Needs | Feasible on CRC Open alone? | What's missing |
|---|---|---|---|
| **General parametric layer** (index, trigger, step payout, basis-risk metrics; MSE or E[U] fit) | Marginal + damage function + basis-risk model, per site | Yes | A basis-risk model, and a value when the output is in currency |
| **RQ1, tail objective** (weighted CVaR against MSE and E[U]) | The same, per site | Yes. The individual scope designs each site on its own, so many sites need no dependence | Only the owner-level KPIs (the total over sites) need dependence |
| **RQ2, joint calibration** (portfolio or cluster scope) | A joint distribution across one owner's sites, plus relative values | No | Dependence, and values or a proxy |
| **Combination** (weighted CVaR on the owner's total) | The same as RQ2 | No | The same as RQ2. Its joint tail years are defined by the dependence model, so the results rest on it most of all |

Plug-in points named in the issue:

- **CRC hazard curves as the index source:** yes. The cleanest Phase 1 hazards are `rx1day` and `rx5day` (declared annual semantics; excess-rainfall covers are an established parametric form). `cyclone` needs the semantics and wind definition first (MAR-41 ask 8).
- **VELO assets as one owner's portfolio:** yes, given values or a proxy and data terms (INVENTORY §2.10). This matters for Phase 2.
- **A parametric playbook or notebook in their format:** yes (§2.4). This is the natural packaging for a showcase.
- **A pipeline step:** a "design a cover" step after `HazardDataset.for_assets(...)`. It reads canonical Parquet and the asset table, and writes payout tables, KPIs and a manifest. It fits their lazy-plan, Parquet-in and Parquet-out style without a change to their code.
- **Their CVaR:** it is complementary, not the same quantity. Theirs is over independent binary branches; ours is over simulated years of a continuous uncovered loss. A showcase should say so plainly (their crosswalk rule: keep unlike metrics apart).

---

## 4. Collaboration options

Each option is shown under two framings:

- **T, the thesis approach:** the two ideas and their combination (weighted-CVaR payout design; joint calibration across one owner's sites), on CRC/VELO data.
- **G, general parametric insurance:** a plain parametric layer (index, trigger, step payout, basis-risk metrics) on CRC hazards, with the thesis methods as an optional add-on.

Effort is agent-and-review time from today's core, assuming core v1 features are on `main`. S ≤ 1 week, M 2–4 weeks, L > 1 month.

### Option A: a showcase in our repository (today's R-02 to R-05 plan)

| | T: thesis approach | G: general parametric layer |
|---|---|---|
| What it shows | The tail objective per site, and joint calibration and the combination for one owner's sites, on CRC hazards | A parametric cover designed on CRC hazards: trigger, payout steps, basis-risk metrics, with the tail objective as one setting |
| CRC must provide | Nothing for a public version on CRC Open plus an open portfolio. For VELO assets: data terms, values or a proxy. For joint scopes: dependence, or acceptance of the IRIS copula | Nothing beyond CRC Open |
| We build | Adapter (MAR-42/43), copula event set (MAR-45), notebook, pipeline and report (MAR-46) | Adapter (MAR-42/43), a single-site annual EventSet with a basis-risk model, notebook, pipeline and report |
| Where | `packages/crc` (AGPL) and `showcase/crc/` (BSD code; outputs CC BY-NC) | the same |
| Licence fit | Clean under ADR 0001. Outputs from CRC Open carry CC BY-NC | the same |
| Effort | L (the copula step and the joint KPIs are the long poles) | M |
| Serves us | Full control; reuses the paper's machinery | A fast first release |
| Serves CRC | A third-party demo they can link to. It doesn't sit in their gallery | the same |

### Option B: a parametric skill, notebook and pipeline in `crc-docs` format, contributed to `crc-docs`

| | T | G |
|---|---|---|
| What it shows | The same science as A, as a CRC "problem" row, e.g. "Design a parametric cover for a site or an owner's sites" | A CRC "problem" row: "Design a parametric cover on a CRC hazard", the parametric twin of `crc-model-flood-insurance-loss` |
| CRC must provide | A contribution route and terms (crc-docs has no licence); review; for T, a dependence source | A contribution route and terms; review |
| We build | A thin `SKILL.md`, a notebook and a pipeline calling our released packages. All logic stays in our library (no library logic in notebooks) | the same, single-site and individual scope only |
| Where | Their repository (skill, notebook, pipeline); our repository (logic) | the same |
| Licence fit | Our core is BSD-3, which is compatible with their AGPL. The skill's terms are whatever crc-docs adopts. Their notebooks depend on AGPL crc-sdk, which is fine for an AGPL or BSD contribution. **Precondition:** our core must be installable, and it isn't on PyPI yet (404 on 2026-11-01) | the same |
| Effort | M–L on top of A | S–M on top of A's adapter |
| Serves us | Reach through their front door and AI skills; a co-branded showcase | the same |
| Serves CRC | A new decision playbook (their P1 gap) and a property-insurance demo (their second domain) | the same, and it is closer to their current scope |

### Option C: an upstream primitive in `crc-framework` or `crc-sdk`

| | T | G |
|---|---|---|
| What it shows | Tail-weighted design and joint calibration as framework functions | A step-payout "transform" and basis-risk metrics as framework functions |
| CRC must provide | Agreement that risk transfer belongs in their framework; Rust review; release slots | the same |
| We build | A port of the LP design (needs an LP solver in Rust/Python) and of the scopes | A payout transform and metrics. No optimiser is needed for fixed triggers |
| Where | Their repositories (AGPL) | the same |
| Licence fit | AGPL-3.0-or-later upstream. As copyright holder of the core, the owner can contribute ported code; the BSD core stays separate | the same |
| Effort | L+ (Rust, solver dependency, their release cadence) | M |
| Serves us | Deep integration, but a second implementation to maintain | Small and visible |
| Serves CRC | A new capability in their core | A building block. Their README says application workflows belong in packages *built on* the framework, which argues against putting design logic upstream |

### Option D: a joint showcase on data RiskThinking provides

| | T | G |
|---|---|---|
| What it shows | The combination on a real owner's sites (a VELO company), with dependence from RiskThinking's own model, if one exists | A multi-site parametric programme on a real asset book, designed site by site |
| CRC must provide | VELO assets with values or definitions; co-simulated fields, event sets or per-year samples; publication terms for both | VELO assets and publication terms |
| We build | A VELO export loader (F6), an EventSet from their samples, and the A pipeline | Loader plus A's G pipeline |
| Where | Our repository; a co-branded report | the same |
| Licence fit | Depends on terms not yet seen (INVENTORY §3.2); possibly results only, no data in the repository | the same |
| Effort | M–L, mostly waiting on data and terms | M |
| Serves us | The strongest RQ2 and combination evidence, since dependence comes from their model rather than ours | A real-asset demo |
| Serves CRC | A VELO "twin" in their six-step demo pattern; enterprise lift | the same |

### Do MAR-42 to MAR-46 still fit?

Mostly yes, re-sequenced into two phases:

- **MAR-42** (assets → `locations`): keep. Make the user-supplied CSV/Parquet asset table, in crc-sdk's `asset_id`, `longitude`, `latitude` contract, the first input. VELO becomes optional (F6).
- **MAR-43** (CRC curves → per-location marginals): keep. It is the heart of Phase 1. Add a sibling step: sample an annual EventSet per site from the marginal, with a damage-function loss and vulnerability draws (§3.1).
- **MAR-44** (IRIS/CLIMADA vs CRC cyclone return levels): not needed for the showcase. It is paper-side model uncertainty and could be lowered in priority.
- **MAR-45** (copula event set): Phase 2 only. It is one of three dependence sources (§3.1). Q1 decides whether it is needed.
- **MAR-46** (notebook, pipeline, report): split into Phase 1 (site-by-site, general framing with the tail objective as a setting) and Phase 2 (one owner's sites, joint scopes). Lay out both in crc-docs skill format from the start, so that Option B costs little.

---

## 5. Recommended approach (agent)

> The agent's recommendation, from public sources only. The choice is Marc's.

**Recommendation: build in our repository, ship in their format (Option A as the engine, Option B as the packaging), framed as general parametric insurance with the thesis methods built in as settings.**

1. **Phase 1, the first small deliverable.** "Design a parametric cover on a CRC hazard."
   - CRC Open `rx1day` (declared annual semantics), or `cyclone` once its semantics are confirmed.
   - One site, or several sites designed one by one.
   - Index = the CRC hazard at the site's cell. Loss = a `crc-framework` damage function × value (or the damage ratio), with vulnerability draws as the basis-risk model.
   - Outputs: a step payout, basis-risk metrics, and the payout under each objective (MSE, E[U], weighted CVaR), with the setup stated.
   - It is delivered as a notebook, a pipeline and a `SKILL.md` in crc-docs layout, and offered to `crc-docs` if RiskThinking wants it.
   - Nothing needs RiskThinking's data or keys.
2. **Phase 2, the full showcase.** One owner's sites, in individual, cluster and portfolio scopes, and the combination.
   - Assets: VELO, or an open book.
   - Dependence: RiskThinking's samples if they exist (Q1), otherwise the IRIS copula (MAR-45), stated as an assumption.
   - RQ2 is presented as method only, under the publication rule.

**Reasons.**

- It fills a gap their own docs name: decision playbooks, insurance, and joint modelling left to the caller. It overlaps nothing they ship.
- Phase 1 needs nothing from them, so it can start before the meeting's outcome is known, and the first deliverable is small.
- The general framing is what a CRC user recognises. Making the objective and scope *settings* of one pipeline keeps both thesis ideas visible without making the showcase depend on them.
- Logic stays in our BSD core and AGPL adapter, so ADR 0001 holds whatever route RiskThinking prefers. A contribution adds only a thin skill.
- It matches their conventions: canonical Parquet in and out, a manifest, visible coverage exceptions. The integration cost on their side is low.

**Main risk: dependence.** CRC has no cross-site dependence. On CRC data, any joint-calibration or combination result would be shaped by the dependence model we choose. That makes Q1 (do they have samples or co-simulated fields?) the most important question for the meeting.

Secondary risks:

- **Basis risk.** On one site it must be modelled explicitly, or the cover is trivially perfect (§3.1).
- **Terms.** `crc-docs` has no licence, CRC Open is NC, and VELO terms are unseen.
- **Release churn.** Pin `crc-sdk`/`crc-framework` and test the minimum versions.

**Fallback: Option A alone.** If RiskThinking prefers not to take a contribution, or the terms aren't settled, the same Phase 1 and 2 stay in our repository. CRC can link to it, and nothing built is lost.

---

## 6. Questions for RiskThinking

A merged list. Items marked **[MAR-41 n]** are already on MAR-41's ask list (access and data for the paper portfolio); they are condensed here, not repeated. The rest are new from this scan. The brief carries the top items.

**Data and method**

- **Q1 (new). Dependence.** Do you have, or plan, event sets, spatially co-simulated annual fields, or the per-year and per-member samples behind the pooled `annual_value_distribution` curves? Could a regional subset be shared for a showcase?
- **Q2 [MAR-41 8].** The cyclone methodology: source model, wind averaging and height, annual maximum or not, and whether VELO `cyclone` equals CRC Open's. New: the same for the probability semantics of `rflood` and `cflood`.
- **Q3 (new). Damage functions.** What are the sources and calibration of the registry impacts (wind tables per country, flood, `rx1day`)? Do you have uncertainty ranges we could use as vulnerability draws? May they be cited as the loss model in a public showcase?
- **Q4 [MAR-41 7].** Field definitions: `asset_value` (currency, basis), `building_footprint` (unit), `materiality_score`, the geocoding method.
- **Q5 (new). Roadmap.** Planned CRC Open releases (other SSPs, a historical baseline), the "future open CDT hazard dataset", and the P0 multi-hazard portfolio orchestration. We want to align with them, not duplicate them.

**Access and terms**

- **Q6 [MAR-41 1, 3, 5].** The API key and credit allowance; entitlement scope (indexes, companies, ownership, pathways); whether responses may pass through an AI tool.
- **Q7 [MAR-41 2, 4, 6].** The licence text per product, written publication permissions (asset-level, anonymised, aggregate; CRC Open figures in a CC BY journal), attribution, and retention of exports.
- **Q8 (new). The non-commercial clause for a showcase.** Is a public parametric showcase on CRC Open, which practitioners may reuse, within CC BY-NC? Would you license a small showcase subset more openly?

**Collaboration route**

- **Q9 (new). Contribution.** Is a parametric skill, notebook and pipeline welcome in `crc-docs`? Under what licence (the repository has none) and what contributor terms? Who reviews?
- **Q10 (new). Co-branding.** May the showcase use the Climate Risk Commons name? Do you want a review before publication, or a joint announcement? How should credit work (All Contributors)?
- **Q11 (new). Use case.** One site, one owner's sites, or a region? Which hazard and geography? Your demos use Toronto, Frankfurt and Cologne; our method work uses the North Atlantic.
- **Q12 (new). Interface.** Would you rather see cover design as a step after `PortfolioEvaluation` (canonical Parquet in and out) or as a stand-alone workflow? Is our AGPL adapter importing `crc-sdk`, with a BSD core, acceptable to you, or would you offer other terms (ADR 0001)?

---

## 7. Unverified points and follow-ups

### Not verified here

- The damage-function calibration sources and their applicability: the registry was read for its factor list only.
- Whether CRC Open curves can be sampled into years that are consistent across hazards at one site. Nothing public says so.
- That a contribution to `crc-docs` would be accepted, or under what terms.
- Anything beyond the public code: VELO data, entitlement and terms stay as in INVENTORY §5.
- No CRC data was downloaded, and no CRC or VELO code was run.

### Proposed follow-ups (for the orchestrator to file; not done here)

- **FU1.** Re-scope MAR-46 into Phase 1 (site by site, general framing with the objective as a setting, `rx1day` first) and Phase 2 (one owner's sites, joint scopes). Lay out both in crc-docs skill format.
- **FU2.** A new issue next to MAR-43: an annual EventSet per site from a CRC marginal, with a `crc-framework` damage-function loss and vulnerability draws as the basis-risk model. Phase 1 can't run without it.
- **FU3.** Make MAR-45 conditional on Q1. If RiskThinking supplies samples or co-simulated fields, build the EventSet from those instead.
- **FU4.** Lower MAR-44's priority for the showcase. It stays useful for the paper.
- **FU5.** A path to install the core from outside this repository (a PyPI pre-release or a pinned git URL). Option B needs it.
- **FU6.** Align `packages/crc` with `crc-sdk`'s Python floor (≥ 3.11), or record why it is ≥ 3.12. It is a one-line decision in the adapter issue.
- **FU7.** Record in `docs/data-sources.md`, once known, which CRC hazards declare `annual_value_distribution` and which don't. This adds to INVENTORY F1.

---

## 8. Sources

All read on 2026-11-01 without sign-in. The repositories were cloned read-only into a scratch directory outside this repository, and nothing from them is vendored here.

| Ref | Source | What it gave |
|---|---|---|
| G1 | `gh api orgs/RiskThinking/repos` (public listing) | Repository list, licences, push dates |
| G2 | [`crc-sdk@532cf448`](https://github.com/RiskThinking/crc-sdk/tree/532cf448a413431a5fd50ca7be0eb129674c3feb): `README.md` (package boundaries, portfolio evaluation, impacts, CRC Open), `pyproject.toml`, `LICENSE`, `docs/licence-policy.md`, `docs/adr/0003-probability-semantics.md`, `crc_sdk/providers/crc_open.py` (release IDs), module tree | §2.1–2.5 |
| G3 | [`crc-framework-rs@6edee70f`](https://github.com/RiskThinking/crc-framework-rs/tree/6edee70f0e3ea754aa2f3ba66c57adb0f2f433e9): `README.md`, `docs/python.md` (impacts, microscores, risk aggregation), `crates/core/src/impact/registry.rs` (factor list), `pyproject.toml`, `Cargo.toml` | §2.3, §2.5 |
| G4 | [`crc-docs@10d4ea8d`](https://github.com/RiskThinking/crc-docs/tree/10d4ea8d01c16ebe3846fecddb391ab32b8be030): `README.md`, `AGENTS.md`, `ai-playbooks/docs/{capability-matrix,gap-backlog,product-strategy}.md`, `.agents/skills/crc-model-flood-insurance-loss/SKILL.md`, `.github/workflows/validate-skills.yml`, `notebooks/`, `pipelines/`, `pyproject.toml` | §2.4–2.6 |
| G5 | [`velo-sdk@ae1aebec`](https://github.com/RiskThinking/velo-sdk/tree/ae1aebec31cd7e831a8a53c594bfa4f426c2b3d6), [`cdt-express-mcp@9795061c`](https://github.com/RiskThinking/cdt-express-mcp/tree/9795061c4c80bbd661ccc00a125fba072fa04d92) (`manifest.json` 0.7.0), [`cdt-express-notebooks@07de3194`](https://github.com/RiskThinking/cdt-express-notebooks/tree/07de3194b0a7eeb1ad2bf1cfefad671e893bbe4c) | §2.1. Content as in INVENTORY §2 |
| G6 | PyPI JSON for `crc-sdk`, `crc-framework`, `velo-sdk`, `parametric-insurance-design` (404) | Versions, release dates, Python floors |
| G7 | `https://data.riskthinking.ai/crc-open/ssp585-global-2026-10-20-v1/_SUCCESS` (HTTP 200) | The release is still served |
| G8 | Grep over the six clones (excluding `.git`, lock files and notebook outputs) for `payout`, `basis risk`, `parametric insurance`, `trigger`, `event set`, `copula`, `stochastic event`, `exceedance curve`, `IBTrACS`, `STORM` | §2.5 "Absent". The only hits were unrelated (CI triggers, "parametric" in the statistical sense, fit fallbacks) and the licence-policy rows for STORM and IBTrACS |
| G9 | PR #12, `showcase/crc/INVENTORY.md` (branch `marcprinzing/mar-41-r-01-inventory-crc-open-and-the-velocdt-asset-database`) and MAR-41's ask list | Built on, not repeated |
