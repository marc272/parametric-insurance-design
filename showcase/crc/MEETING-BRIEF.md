# Meeting brief: parametric insurance on Climate Risk Commons

*For a first planning meeting with the RiskThinking / Climate Risk Commons team, November 2026. It covers method and tooling only. It reports no results. The evidence and sources are in [`COLLABORATION-SCAN.md`](COLLABORATION-SCAN.md).*

## The pitch

1. A parametric cover pays an agreed amount when a measured hazard index crosses a trigger. Its main input is what Climate Risk Commons publishes: transparent, versioned hazard distributions at a location.
2. [`parametric-insurance-design`](https://github.com/marc272/parametric-insurance-design) is an open-source library (BSD-3-Clause) that designs step payouts from an index and a loss model and reports basis-risk metrics. It offers two design choices from a master's thesis:
   - a tail-weighted objective (a weighted CVaR of the uncovered loss);
   - joint calibration across one owner's sites.
3. We propose to add "design a parametric cover" as a new Climate Risk Commons workflow, built on `crc-sdk` and `crc-framework`. It would start with single sites on CRC Open and grow to a multi-site showcase.

## Recommended approach

**Build in our repository, ship in your format.**

- The design logic lives in our library and in an AGPL adapter that imports `crc-sdk`.
- The showcase is laid out like a `crc-docs` problem: a skill, a notebook, a headless pipeline and a report with a provenance manifest. We offer it to `crc-docs` if you want it there.
- It is framed as general parametric insurance: index, trigger, step payout, basis risk. The thesis methods are settings of the same pipeline, not a separate product:
  - the objective: MSE, expected uncovered loss, or weighted CVaR;
  - the scope: each site alone, clusters, or the owner's whole portfolio.

**Fallback.** The same showcase stays in our repository, and Climate Risk Commons links to it. Nothing built is lost.

## Phased plan

| Phase | Deliverable | Needs from RiskThinking |
|---|---|---|
| **1. First small deliverable** | "Design a parametric cover on a CRC hazard". CRC Open `rx1day`, or `cyclone` once its definition is confirmed. One site, or several sites designed one by one. Index = the CRC hazard at the site's cell. Loss = a `crc-framework` damage function, with vulnerability uncertainty as the basis-risk model. Outputs: payout tables, basis-risk metrics and the design under each objective, all with the setup stated | Nothing to start. Your view on the hazard and the use case |
| **2. Full showcase** | One owner's sites, designed site by site and jointly (cluster and portfolio scopes), including the tail objective on the owner's total. Assets: VELO/CDT or an open asset book | Asset data and terms, and above all a source of dependence between sites (asks 1 and 3) |

## Asks to RiskThinking

1. **Data.**
   - Dependence: do you have event sets, spatially co-simulated annual fields, or the per-year and per-member samples behind the pooled curves? Could a regional subset be shared?
   - Hazard definitions: the methodology of the `cyclone` layer (source model, wind averaging and height, annual maximum or not), and the probability semantics of the flood layers.
   - Damage functions: the sources, calibration and uncertainty ranges of the registry damage functions.
2. **Licence terms for publishing.**
   - The terms for each product (CRC Open, VELO/CDT assets, VELO/CDT hazards).
   - What may be published: asset-level, anonymised, aggregate.
   - Whether a public showcase on CRC Open falls within CC BY-NC, and whether a small showcase subset could be licensed more openly.
   - Attribution text.
3. **Field definitions.**
   - `asset_value`: currency and basis.
   - `building_footprint`: unit.
   - `materiality_score`.
   - The geocoding method and coordinate precision.
4. **A contribution or co-branding route.**
   - Is a parametric skill, notebook and pipeline welcome in `crc-docs`? The repository has no licence file. Under what licence and contributor terms, and who reviews?
   - May the showcase use the Climate Risk Commons name, and do you want a review before publication?
5. **Access**, for the VELO part:
   - an API key and the credit allowance;
   - entitlement scope (indexes, companies, ownership, pathways);
   - whether responses may pass through an AI tool.

## Open questions for the meeting

- Which use case matters most to you: one site, one owner's sites, or a region? Which hazard and geography?
- Should cover design be a step after `PortfolioEvaluation` (canonical Parquet in and out), or a stand-alone workflow?
- Is an AGPL adapter importing `crc-sdk`, with our BSD core, the right split for you?
- Roadmap: new CRC Open releases (other scenarios, a historical baseline), the planned open CDT hazard dataset, and multi-hazard portfolio orchestration. We'd like to align with these, not duplicate them.

*On publishing: every number we publish will state its setup (portfolio, basis, basis-risk model, pricing, train/test split) and come from out-of-sample runs. We make no general claim that tail-weighted designs outperform. Joint calibration is presented as a method only, with no comparative claim.*
