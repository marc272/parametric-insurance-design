# Literature notes (MAR-28)

**Status: draft for owner review.** This file has one short paragraph per reference in [`references.bib`](references.bib), followed by observations O1–O6, a list of works considered but not included, and a log of how each reference was checked. Every summary is a paraphrase. Nothing here claims that one design performs better than another (publication rule).

Notation follows SPEC §6: L is the loss, π the payout, U = (L − π)⁺ the uncovered loss, and P the premium.

## Core references (named in the issue)

**`steinmann2023framework`: Steinmann, Guillod, Fairless & Bresch (2023), *Environment Systems and Decisions*.**
- *What it does:* an open CLIMADA workflow for parametric design. Hazard and exposure define the index, and a family of payout functions plays the role of the impact function. Candidate products are combinations of a cat-in-a-circle radius (10–50 km around each hospital) with step payouts on Saffir–Simpson categories in 25 % increments. The authors pick the product with the lowest RMSE between modelled damage and payout, with basis risk summed over all affected hospitals for each event. The chosen product is then checked on historic events and under Knutson-scaled TC projections at two warming levels. The case studies are TC hospitals in Mozambique and winter storms in France.
- *Why RMSE:* the authors pick RMSE over a relative error measure because it gives large-impact events more weight, which they argue matters for post-disaster liquidity.
- *What it does not do:* there are no per-asset parameters (one product serves all sites), no tail functional, no premium in the design, and no design against the climate scenarios.
- *Relevance:* closest prior work for all three claims, and the natural CLIMADA anchor.

**`maier2026expectiles`: Maier & Scherer (2026; arXiv 2025), *European Actuarial Journal*.**
- *What it does:* penalises over- and under-compensation with different weights in a squared-error criterion. Under that criterion, the basis-risk-optimal payments for both pure parametric and index contracts are conditional expectiles of the true loss, given the triggering event. The paper links these payments to stochastic orders, estimates them by regression, and illustrates them on cyber and agricultural covers.
- *What it does not do:* the aggregation over events is a plain mean, and the design covers a single policyholder.
- *Relevance:* the closest prior work on asymmetric basis-risk penalties (claim A).

**`maier2026weighting`: Maier & Scherer (2026), arXiv 2604.21372.**
- *What it does:* treats the expectile weight as unknown and characterises when an optimal weight exists and is unique under expected utility, using two boundary conditions. Where no optimum exists, it compares the contract with no insurance and with full indemnity. The simulation uses a cat-in-a-circle hurricane cover on STORM tracks with a synthetic loss model. The optimal weight rises with risk aversion and falls with premium loading.
- *Dependence:* the authors find strong tail dependence of wind speeds between policyholders. They list a joint, multi-policyholder perspective (for example risk sharing between nations) as future work.
- *Relevance:* claim A (individual-level design) and claim C (cat-in-a-circle with premium loading). Both authors are at the TUM Chair of Mathematical Finance, where the thesis was examined.

**`gao2026basisrisk`: Gao, Yang & Liu (2026; arXiv 2409.16599), *Geneva Papers*.**
- *What it does:* a stylised Monte Carlo study on the unit square. Each contract has a binary trigger: it pays when a circular event footprint covers a reference weather station above a fixed severity threshold, and the insured site may or may not be hit. The authors measure the average annual basis risk relative to premium, and its spread, for pools of independent contracts. The portfolio basis ratio and its volatility fall as the number of contracts grows. Site–station–footprint geometry matters, and severity has no significant effect.
- *What it does not do:* no payout optimisation and no single owner.
- *Relevance:* evidence that diversification of basis risk exists. Claim A moves diversification *into* the design.

**`louaas2024design` / `louaas2026design`: Louaas & Picard (HAL 2024; *Geneva Risk and Insurance Review* 2026).**
- *What it does:* a microeconomic theory of parametric insurance under asymmetric information. The loss is private, so the payout can depend only on a public parameter vector. That vector yields a loss index (the best estimate of the loss), and basis risk is the residual.
- *Main result:* the optimal design depends on whether the index and the basis risk are independent. If they are, results from insurance demand under independent background risk carry over. For example, under a constant loading a straight deductible on the loss index is optimal. Risk aversion and prudence shape demand.
- *What it does not do:* the setting is a single policyholder with expected utility. There are no tail measures and no computation.
- *Relevance:* the expected-utility strand, against which the paper's "demand-informed heuristic" (the thesis's own term) should be framed. Content was read in the 2022 version; see the verification log.

## CVaR and robust optimisation

**`rockafellar2000cvar`, `rockafellar2002cvar`: Rockafellar & Uryasev.**
- *What they do:* write CVaR as the minimum over an auxiliary threshold of a convex function. Over scenarios this turns CVaR minimisation into an LP. The 2002 paper extends the results to general distributions with atoms, which matters for event sets with many zero-loss rows.
- *Relevance:* the basis of the LP in claims A and B.

**`zhu2009worst`: Zhu & Fukushima (2009).**
- *What it does:* minimises worst-case CVaR when the distribution is only partly known (a mixture of candidate distributions, box sets or ellipsoidal sets), as LPs or SOCPs, with portfolio-selection examples.
- *Relevance:* R1, the min–max over scenario event sets, is the mixture case of this approach. Claim B's novelty therefore lies in the application, not the technique.

**`bental2013robust`: Ben-Tal, den Hertog, De Waegenaere, Melenberg & Rennen (2013).**
- *What it does:* robust linear optimisation with uncertainty sets on probability vectors defined by φ-divergences (χ² among them), which arise as statistical confidence sets. The robust counterpart is tractable for most common choices of φ.
- *Relevance:* the reference for R2 with a χ² ball. The abstract does not name total variation. The L1 case is covered by Jiang & Guan.

**`jiang2018riskaverse`: Jiang & Guan (2018).**
- *What it does:* distributionally robust two-stage programs. The worst-case expectation over an L1-norm (total-variation) ambiguity set reduces to a convex combination of CVaR and the essential supremum. As data grow, the problem moves from robust towards risk-neutral.
- *Relevance:* direct consequences for R2-TV (O2).

**`bertsimas2004price`: Bertsimas & Sim (2004).**
- *What it does:* robust LPs with uncertainty budgets that control how conservative the solution is. It is the source of the term "price of robustness".
- *Relevance:* SPEC §6.5 uses the term with its own meaning (premium or E[U] given up for tail basis risk saved under misspecification). The manuscript should define it explicitly.

## Sovereign pools and cat-in-a-circle practice

**`ccrif2026about`: CCRIF SPC website.**
- *What it is:* a parametric facility for Caribbean and Central American governments, started in 2007 and restructured in 2014 as a Cayman segregated portfolio company. Its members also include utilities. It covers tropical cyclones, earthquakes, excess rainfall, and products for utilities and fisheries. Payouts are tied to modelled losses relative to an attachment point.
- *Relevance:* the canonical sovereign pool. It is multi-owner, so cross-coverage of the kind the portfolio scope uses does not carry over without a risk-sharing rule (SPEC M5).

**`ciullo2023pooling`: Ciullo, Strobl, Meiler, Martius & Bresch (2023).**
- *What it does:* forms sovereign catastrophe pools by maximising risk diversification and compares global with regional pooling. Global pooling raises diversification and spreads countries' risk shares more evenly.
- *Relevance:* pool composition, not payout design. Shows that the Bresch group (CLIMADA) studies pool-level diversification, which is useful context for the CLIMADA stream.

**`franco2024typology`: Franco et al. (2024), *Mathematics*.**
- *What it does:* classifies single-domain triggers (cat-in-a-box, cat-in-a-circle) and multi-domain triggers (cat-in-a-grid) for TC risk transfer, and describes calibration with a cat model. In a Miami case study, a grid trigger shows less basis risk than a single box.
- *Relevance:* the reference for cat-in-a-circle practice (O3). The thesis cites it under the wrong surname (O4).

## Directly adjacent works (found while checking the core list; all are cited in the thesis)

**`fan2023tail`: Fan, Tan & Zhang (2023), *IME*.**
- *What it does:* proposes a gradient-free random search (model-based annealing random search) for tail-risk objectives, which are hard to optimise (VaR is non-convex). The illustration designs a weather index insurance for Illinois corn with VaR, CVaR and EVaR as objectives.
- *Per the thesis (not re-checked in the paywalled full text):* the objective is the hedged loss L − π + P, and CVaR held up well out of sample against VaR and EVaR.
- *Relevance:* the closest prior work for a tail objective in index design (claim A; see O1).

**`lopez2025hybrid`: Lopez & Nkameni (2025), arXiv 2507.18207.**
- *What it does:* a hybrid contract with indemnity cover up to a limit and a parametric layer above it, driven by covariates available right after the event. The parametric part is calibrated with a criterion built for Pareto-type tails, where the expected loss may be infinite. The paper gives convergence rates, simulations and a US tornado application.
- *Relevance:* its tail focus comes from the contract's layer structure rather than from a tail functional (claim A, background).

**`birghila2019xl`: Birghila & Pflug (2019), *IME*.**
- *What it does:* contract design under ambiguity about the loss distribution. The policyholder minimises a distortion risk measure of the retained loss under a premium limit, with the premium computed on a baseline distribution and ambiguity as a neighbourhood around it. Under AVaR, an entrance-excess-of-loss contract is optimal. The authors introduce a Wasserstein-type distance that is finer in the tails.
- *Relevance:* the indemnity analogue of claim B. It also uses the same "price on the baseline" convention as R1 (premium on S₀).

## Base work

**`prinzing2026thesis`: Prinzing (2026), master's thesis, TUM.**
- *What it does:* the weighted objective α·CVaR_β(U) + (1−α)·E[U] on the uncovered loss, with individual, cluster and portfolio scopes, step payouts, an LP via Rockafellar–Uryasev, and a 9-asset Miami case on IRIS/CLIMADA with a noise layer.
- *How it frames its novelty:* the thesis taxonomy (its Fig. 2.2) places prior work on two axes, symmetric vs. asymmetric basis risk and expectation vs. tail aggregation, and claims the empty asymmetric × tail cell.
- *Relevance:* see O1 for a caveat on that cell. SPEC §3.2 lists the method issues that v2 fixes.

## Observations for the owner

These are observations, not conclusions. The interpretation is the owner's.

**O1. When the one-sided measure matters.**
- *Quantile form:* for any loss X, CVaR_β(X) is the average of its quantile function q_X(u) over u in (β, 1). Because x ↦ x⁺ is continuous and non-decreasing, the quantiles of X⁺ are (q_X(u))⁺. So CVaR_β(X⁺) = CVaR_β(X) exactly when q_X(u) ≥ 0 for almost every u > β. For X = L − π this fails only if over-compensation (L < π) carries more than a fraction β of the probability mass.
- *Translation equivariance:* CVaR also satisfies CVaR_β(L − π + P) = CVaR_β(L − π) + P, and P is the same for every feasible design when the premium budget binds.
- *Consequence:* at event level, the tail term α·CVaR_β(U) has the same minimisers as a CVaR of the signed, hedged residual of the kind the thesis attributes to Fan et al. This holds both per asset and for the portfolio aggregate, because the same argument applies to the summed residual.
- *Where one-sidedness matters:* (a) the E[U] term when α < 1; (b) the annual basis of SPEC §6.2, where U_y = Σ_{e∈y}(L_e − π_e)⁺ is a sum of per-event shortfalls, so an over-payment in one event cannot offset a shortfall in another event of the same year.
- *Implication:* the "asymmetric × tail" cell is a weaker basis for novelty than the multi-asset joint design and the exact LP.

**O2. R2 with a total-variation ball.**
- *Result:* by Jiang & Guan (2018), the worst case of E[U] over an L1 (TV) ball around the empirical year weights is a convex combination of a CVaR of U and max U. R2-TV applied only to E[U] therefore gives a reweighted tail objective close to the nominal family.
- *Caveat:* only the abstract was read, so the exact weights and CVaR level are not checked.
- *Implication:* R2 would add something distinct if it is applied to the full weighted objective or uses a χ² ball. This bears on D6 (MAR-29).

**O3. Index (b) in SPEC §6.3 is established practice.**
- *Prior use:* the cat-in-a-circle index (maximum Saffir–Simpson category within radius r) is the index Steinmann et al. use. Maier & Scherer (2026b) use a cat-in-a-circle wind index on STORM tracks, and Franco et al. (2024) review the trigger family.
- *Implication:* present it as realism, not novelty. Reusing Steinmann's radii and payout family as a reference configuration would help comparison and the CLIMADA contribution.

**O4. Thesis bibliography fixes for the manuscript (MAR-39).**
- Thesis ref. [29]: "F. Guillermo et al." should be Franco, G. et al. (2024). Refs. [27] and [28] look like the same given-name/surname swap, but this was not checked.
- Ref. [10]: Chen et al. is dated 2024, 70(7):4306–4327 in Crossref; the thesis gives 2023.
- Refs. [42] and [43] now have journal volumes and pages (see `louaas2026design` and `maier2026expectiles`).

**O5. Steinmann et al. already aim at large events.** They chose RMSE because it emphasises large-impact events. The paper can present the weighted CVaR as an explicit, tunable form of that same intent, rather than as a break with it.

**O6. Steinmann's selection rule as a special case.** One product shared by all sites and chosen on basis risk summed over sites is, in our terms, a single cluster with a common payout under an RMSE criterion. It is a natural bridge between the CLIMADA module and the cluster scope.

## Considered, not included

| Work | Identifier | Why not included |
|---|---|---|
| Lopez & Thomas (2023), heavy-tailed claims and parametric cover | arXiv 2301.07776 (verified) | Theory of coverage gaps under heavy tails. Background only, not needed for the three claims |
| Zhang, Tan & Weng (2019), *Index insurance design*, ASTIN Bulletin 49(2):491–523 | doi:10.1017/asb.2019.5 (verified) | Expected-utility design with non-linear payouts. Louaas & Picard cover the expected-utility strand for positioning |
| Chen, Lu, Zhang & Zhu (2024), neural-network index insurance, *Management Science* 70(7):4306–4327 | doi:10.1287/mnsc.2023.4902 (verified) | Expected-utility design for one region. Not tail-based or multi-asset |
| Miki et al. (2025), tsunami parametric basis risk, *npj Natural Hazards* 2:67 | doi:10.1038/s44304-025-00127-x (verified) | Optimises threshold, index and payout for one port. The thesis says it uses a TVaR constraint, which the abstract does not confirm |
| Avanzi, Kusch Falden & Steffensen, parametric vs. indemnity under budget limits | arXiv 2512.21973 (verified) | Mean–variance welfare comparison of contract types, not a payout-design method |
| Huang, Ma, Guo & Gu, parametric design for power systems | arXiv 2608.15023 (verified) | Includes CVaR of unserved energy among the design criteria, but for a single grid, with a non-financial loss and a library search |
| Niakh, Bassière, Denuit & Robert (2025), peer-to-peer basis risk sharing, *Annals of OR* | doi:10.1007/s10479-025-06987-w (verified) | Multi-owner sharing of basis risk. Adjacent to pools, not to single-owner design |
| Rahimian & Mehrotra (2022), DRO survey, *Open J. Math. Optim.* 3:4 | doi:10.5802/ojmo.15 (verified) | Survey; useful when writing R2, not needed for positioning |
| Birghila, Pflug & Hochrainer-Stigler (2022), risk layering under ambiguity, *Risk Analysis* 42 | doi:10.1111/risa.13884 (seen in a Crossref search only) | Further DRO work on indemnity layering. Birghila & Pflug (2019) is the closer analogue |
| Boonen & Jiang (2025), Wasserstein-robust insurance; Jiang, Zhang & Zhang, Bregman–Wasserstein DRO insurance | arXiv 2604.27837 for the latter; metadata **not verified** (search results only) | More DRO indemnity work. Check before citing |
| Stigler & Lobell (2024), zonal basis risk, *AJAE* 106(1) | metadata **not verified** (taken from the thesis bibliography) | Relevant to the zonal trade-off in the cluster scope, but not to the three claims |

## Verification log

| Key | Metadata checked against | Content read |
|---|---|---|
| `steinmann2023framework` | Crossref (DOI) | Research Square preprint v2, methods and case study. The publisher PDF needs a sign-in redirect |
| `maier2026expectiles` | Crossref (DOI) + arXiv API | Abstract only |
| `maier2026weighting` | arXiv abstract page + API | Full text v1 (introduction, §4, conclusion) |
| `gao2026basisrisk` | arXiv API + Crossref (DOI) | arXiv full text v1. Journal version not compared |
| `louaas2024design` | HAL API (hal-04511811) | 2022 EGRIE version (introduction, conclusion). hal.science blocked automated access |
| `louaas2026design` | Crossref (DOI) | Not read |
| `rockafellar2000cvar`, `rockafellar2002cvar` | Crossref (DOI) | Not re-read. Content is standard and used in the thesis |
| `zhu2009worst`, `bental2013robust`, `jiang2018riskaverse` | Crossref (DOI) | Abstracts (Crossref) |
| `bertsimas2004price` | Crossref (DOI) | Not read. Cited for the term only |
| `ccrif2026about` | ccrif.org page | Page text |
| `ciullo2023pooling`, `franco2024typology` | Crossref (DOI) | Abstracts (Crossref) |
| `fan2023tail` | Crossref (DOI) + RePEc/IDEAS | Abstract only (paywalled). The objective details come from the thesis |
| `lopez2025hybrid` | arXiv abstract page + API | Abstract only |
| `birghila2019xl` | Crossref (DOI) | Abstract (IIASA repository) |
| `prinzing2026thesis` | Thesis PDF title page | Chapters 1–2, chapter 6 and the bibliography |

**Searches run (2026-10-25):**
- distributionally robust index insurance design;
- robust parametric insurance under climate scenarios (min–max);
- "basis risk" with "robust optimization" for parametric or index payouts (extended search);
- joint multi-asset parametric payout optimisation for one owner (extended search).

None of these searches found a robust or DRO design of parametric (index) payouts, or a single-owner joint multi-asset tail design. That is absence of evidence from a bounded search, not proof of novelty.

## Addendum (MAR-75): targeted search for robust design of index-based payouts

**Status: draft for owner review.** Prepared for [MAR-75](https://linear.app/marc-prinzing/issue/MAR-75/p-09-targeted-search-robust-and-distributionally-robust-design-of) on 2026-10-25. The MAR-28 search found no robust or distributionally robust (DRO) design of index-based payouts, so claim B's "first" needed a fuller search before the manuscript (MAR-39). This addendum records that search: sources, verbatim queries, forward citations, a classification of every relevant hit, observations O7–O11, and a proposed wording for claim B. Nothing above this heading was changed. Every summary is a paraphrase. These are observations, not conclusions; the owner decides.

### Sources and access (2026-10-25)

| Source | Used for | Access |
|---|---|---|
| Scopus | Not used | Not reachable without an account (HTTP 403 on the search URL) |
| Google Scholar | Three keyword queries (G1–G3) | First result page read once per query. A fourth automated request was refused by this session's permission policy, which treats scripted Scholar access as bot-check circumvention, so Scholar was not used further |
| OpenAlex API (anonymous) | Keyword queries on title and abstract (`title_and_abstract.search` filter, relevance-sorted); forward citations (`cites:` filter); abstracts | Rate-limited (HTTP 429) several times. Queries were re-run after a pause; one query was never run (see the table) |
| Semantic Scholar Graph API (no key) | Forward citations (`/paper/{id}/citations`) | Citation endpoint worked for four of the five seeds. The keyword search endpoint returned HTTP 429 every time, so it was not used |
| Crossref API | Keyword queries (`query.bibliographic`, top rows screened); metadata and deposited abstracts of every new bib entry | Open |
| arXiv API | Keyword queries; metadata of arXiv entries | Open |
| General web search | Cross-checks (W1–W8) | Open |
| Publisher pages | Abstracts | ScienceDirect and SSRN returned HTTP 403, and Springer redirected to a sign-in page, which was not followed. Abstracts were taken from Crossref, OpenAlex (publisher abstract), RePEc/IDEAS or arXiv instead |

### Keyword queries (all run on 2026-10-25, recorded verbatim)

"Hits" is the count that the source reported. Crossref ranks its whole index, so its totals mean nothing; only the top rows were screened.

| ID | Source | Query | Hits | Relevant hits (classification below) |
|---|---|---|---|---|
| G1 | Google Scholar | `"distributionally robust" "index insurance"` | 1 on the first page | `sadefokamdem2026robust` |
| G2 | Google Scholar | `"distributionally robust" "parametric insurance"` | 4 | `sadefokamdem2026robust`; the other three are unrelated (supply-chain cat bond, utility reserve fund, wind-turbine storms) |
| G3 | Google Scholar | `"robust optimization" "index insurance" design` | 5 | `sadefokamdem2026robust`; Zhou et al. (2026); the other three are unrelated water-resources planning works |
| O1 | OpenAlex | `"distributionally robust" AND (insurance OR "basis risk")` | 34 | `boonen2025wasserstein`, `jiang2026bregman`, `birghila2019xl`, Zenodo cluster, Tsekrekos et al. (2026) |
| O2 | OpenAlex | `("index insurance" OR "index-based insurance" OR "parametric insurance" OR "weather derivative" OR "parametric trigger") AND (robust OR ambiguity OR "worst-case" OR "model uncertainty")` | 196 (top 50 screened) | `sadefokamdem2026robust`, Fujii & Osaki (2020), Diao, Weng & Zhang (2026), Lopez & Nkameni (2026) |
| O3 | OpenAlex | `"basis risk" AND ("robust optimization" OR "robust optimisation" OR minimax OR "min-max" OR "worst case" OR "worst-case" OR "distributional uncertainty")` | 7 | `sadefokamdem2026robust`, `lefevre2021sconvex`, Zenodo cluster |
| O4 | OpenAlex | `("index insurance" OR "parametric insurance" OR "index-based insurance" OR "catastrophe bond" OR "parametric trigger") AND ("climate scenarios" OR "climate change scenarios" OR "climate projections" OR "hazard catalogue" OR "event set" OR "stochastic catalog") AND (design OR optimal OR optimization)` | **not run** (HTTP 429). O5 and O8 cover its climate terms; its catalogue terms are covered only by W3 | n/a |
| O5 | OpenAlex | `("index insurance" OR "index-based insurance" OR "parametric insurance" OR "weather index") AND ("climate change" OR "climate projections" OR "climate scenarios" OR "nonstationary" OR "non-stationary") AND (design OR "optimal contract" OR trigger OR payout)` | 236 (top 50 screened) | `daron2014assessing`; Enenkel et al. (2017, EGU abstract); Mazviona & Sølvsten (2025); Feleppa (2026) |
| O6 | OpenAlex | `("catastrophe bond" OR "cat bond" OR "parametric trigger" OR "cat-in-a-circle" OR "cat-in-a-box" OR "index-based risk transfer") AND (robust OR ambiguity OR "worst-case" OR minimax OR "model uncertainty") AND (design OR optimal OR optimization)` | 13 | None |
| O7 | OpenAlex | `(Wasserstein OR "phi-divergence" OR "minimax regret" OR "ambiguity set" OR "scenario-based robust") AND ("crop insurance" OR "agricultural insurance" OR "index insurance" OR "weather insurance" OR "parametric insurance" OR "basis risk" OR "disaster insurance" OR "catastrophe insurance")` | 11 | `sadefokamdem2026robust`, Tsekrekos et al. (2026), Zenodo cluster |
| O8 | OpenAlex | `("index insurance" OR "parametric insurance" OR "index-based insurance" OR "weather index insurance") AND (scenarios OR "scenario set" OR "climate model ensemble" OR "multi-model") AND (optimization OR optimisation OR "optimal design") AND (robust OR "worst" OR "out-of-sample" OR "misspecification")` | 4 | None |
| A1 | arXiv | `(abs:"index insurance" OR abs:"parametric insurance" OR abs:"index-based insurance" OR abs:"basis risk") AND (abs:robust OR abs:"distributionally robust" OR abs:ambiguity OR abs:"worst-case" OR abs:minimax)` | 4 | Lopez & Nkameni (2026) only, which is not robust design |
| A2 | arXiv | `(abs:insurance OR abs:reinsurance OR abs:"catastrophe bond") AND (abs:"distributionally robust" OR abs:"scenario-robust" OR abs:"robust optimization")` | 15 | `bertsimas2024catastrophe`, `jiang2026bregman` |
| C1 | Crossref | `robust parametric insurance design basis risk ambiguity` | top 30 screened | `sadefokamdem2026robust`, `dietz2021pricing`, Fujii & Osaki (2020), Lu & Tang (2026) |
| C2 | Crossref | `distributionally robust index insurance contract design` | top 30 screened | `boonen2025wasserstein`, Lu & Tang (2026), Liu & Mao (2022) |
| C3 | Crossref | `robust optimization weather index insurance crop basis risk minimization` | **not run** (HTTP 429). Covered in part by O2, O3 and W2 | n/a |
| C4 | Crossref | `catastrophe models insurance decision making under ambiguity` | top 5 screened | `sadefokamdem2026robust` |
| W1 | Web search | `distributionally robust optimization index insurance design basis risk` | 9 links | `jiang2026bregman`; no robust index design |
| W2 | Web search | `robust optimization weather index insurance contract design worst-case scenarios` | 9 links | `asimit2017robust`; no robust index design |
| W3 | Web search | `parametric insurance payout design climate change scenarios robust hazard catalogue uncertainty` | 10 links | `steinmann2023framework` (ex-post check only), Assa (2026), Huang et al. (2026) |
| W4 | Web search | `Sadefo Kamdem "Robust Parametric Insurance Design" catastrophe-model ambiguity` | 9 links | The paper itself was not indexed. `dietz2021pricing` was |
| W5 | Web search | `"index insurance" "robust" design "multiple models" OR "ensemble of models" OR "model ambiguity" basis risk payout optimization` | 9 links | None |
| W6 | Web search | `min-max CVaR parametric insurance design scenarios linear programming basis risk tropical cyclone` | 9 links | None (Huang et al. use CVaR over scenarios, but not a worst case across scenario sets) |
| W7 | Web search | `"index insurance" design "convex optimization" OR "linear program" payout function optimal contract data-driven` | 9 links | None robust. Monopoly pricing of weather index insurance (arXiv 2512.01623) uses a farmer CVaR, which bears on claim A rather than B (follow-up) |
| W8 | Web search | `Asimit Hu Xie "Optimal robust insurance with a finite uncertainty set" abstract` | 10 links | Used to find the open abstract of `asimit2019finite` |

Further web searches were used only to look up abstracts of known hits (Lu & Tang 2026, Fujii & Osaki 2020, Zhou et al. 2026). None of them found the abstract.

### Forward citations (2026-10-25)

| Seed | OpenAlex | Semantic Scholar | Relevant citers |
|---|---|---|---|
| `birghila2019xl` (W2947256753) | 20 citers, all screened | 20 citers, all screened | All robust or DRO **indemnity** or reinsurance design. In the bib: `boonen2025wasserstein`. Also Cai, Liu & Yin (2024, 2025); Xie, Liu & Mao (2023); Boonen & Jiang (2022, 2024, 2025); Birghila, Boonen & Ghossoub (2023); Jiang, Escobar-Anel & Ren (2020); Landriault, Liu & Shi (2025); Jiang, Mao & Xiong (2025); Wang & Zhang (2025). Timonina-Farkas (2025) is flood risk management by multistage stochastic programming, not contract design |
| `zhu2009worst` (W2118856090) | 510 citers. Filtered with `title_and_abstract.search:insurance` (18) and with `index OR weather OR parametric OR "basis risk" OR catastrophe OR agricultural` (47) | 570 citers, titles filtered by the regex `insur\|index\|weather\|parametric\|basis\|catastroph\|crop\|agri\|disaster\|climat\|hazard\|hurrican\|cyclon\|flood` (37 shown) | `asimit2017robust`, `asimit2019finite` (indemnity). The rest is portfolio selection, index *tracking* (stock indices) and DRO disaster-relief logistics: unrelated |
| `steinmann2023framework` (W4386351804) | 12 | 12 | `sadefokamdem2026robust`. The others (Franco 2024, Lemke et al. 2025, Chen et al. 2026, Men et al. 2025, Bergmüller et al. 2026, and others) do trigger design, loss prediction or pooling, with no robust design |
| `maier2026expectiles` (W4415031982) | 2 | 4 | `sadefokamdem2026robust`. Also `maier2026weighting`, Avanzi et al. (2025), and an EAJ issue presentation |
| `maier2026weighting` (W7155549997) | 0 | not retrieved (HTTP 429 twice) | None found |
| Second level: `asimit2017robust` (W2516279781), `asimit2019finite` (W2786661519) | 2017: 1 citer matches the index-topic filter (portfolio selection, unrelated). 2019: 16 citers, all screened | not run | `birghila2022layering` (a 2019 citer). The rest are indemnity or reinsurance |

### Classification of relevant hits

Classes, as the issue defines them: **P** = robust design of index payouts (prior art for B); **I** = robust design of indemnity contracts; **U** = unrelated to robust payout design. The *Read* column says what was read: **abs** = abstract, **text** = a model section, **title** = title and venue only.

| Work | Class | What it does (paraphrase) | Read |
|---|---|---|---|
| `sadefokamdem2026robust` (SSRN preprint, Crossref record created 2026-10-18) | **P** | The joint law of the true need D and a parametric index X lies in a convex set of plausible catastrophe models. Under a worst-case asymmetric basis-risk criterion it proves that an optimal attachment–exhaustion–limit contract exists. For unrestricted index-contingent payments, the robust payment is a capped conditional expectile under a least-favourable prior. For layer contracts the expected payout depends on the model only through the survival function of X on the layer, which gives a model-disagreement measure (LMUI) and a "contractual filtering" interpretation. Also comparative statics in ambiguity aversion and Wasserstein sensitivity bounds. Analytic examples; an El Salvador earthquake illustration is "specified … conditional on reproducible public inputs" | abs |
| `asimit2017robust` | I | Robust indemnity contracts when the loss distribution is uncertain: worst-case-scenario and worst-case-regret models with VaR and CVaR objectives. Closed form for VaR worst case, LP formulations otherwise. Also discusses Pareto optimality of robust solutions | abs |
| `asimit2019finite` | I | Robust indemnity or reinsurance contracts over a finite set of candidate models. Several robust models (among them weighted-average and weighted-worst-case) solved as SOCPs. Numerical results favour picking the best-fitting model with large samples and the weighted robust models with small samples | abs (IDEAS) |
| `birghila2019xl` (MAR-28) | I | See the MAR-28 entry above | abs |
| `boonen2025wasserstein` | I | Indemnity function that minimises the worst-case convex distortion risk measure over a p-Wasserstein ball around a benchmark loss law, with an expected-value premium. Explicit optimal indemnity and worst-case distribution | abs |
| `jiang2026bregman` | I | Two indemnity problems over a Bregman–Wasserstein ball: α-maxmin VaR demand, and worst-case distortion risk under a VaR constraint. Closed forms with a TVaR example | abs |
| `birghila2022layering` | I | Indemnity risk layers under ambiguity, motivated by changing climate risk, with distortion risk measures. Closed form. Drought case for Austrian farmers, with subsidies | abs |
| `bertsimas2024catastrophe` | I (pricing) | Adaptive robust optimisation of state-level premiums for the US NFIP. Uncertainty sets come from historical statistics and from ML-predicted flood probabilities, the latter as a stand-in for climate-amplified risk. Payouts are indemnity claims; contract shape is not a decision | abs + text |
| `dietz2021pricing` | I (pricing) | α-maxmin insurance pricing over two hurricane catastrophe-model datasets: ambiguity loads, and a comparison with model blending | abs |
| Other indemnity or reinsurance DRO found through the citation chains: Cai, Liu & Yin (2024, EJOR); Xie, Liu & Mao (2023, ASTIN); Liu & Mao (2022, IME); Boonen & Jiang (2024, 2025, EJOR); Birghila, Boonen & Ghossoub (2023, F&S); Jiang, Escobar-Anel & Ren (2020, ASTIN); Landriault, Liu & Shi (2025, ASTIN); Jiang, Mao & Xiong (2025, NAAJ); Lu & Tang (2026, IME 129:103271) | I | Titles and venues indicate robust indemnity or reinsurance design. Lu & Tang's abstract was not reachable | title |
| `lefevre2021sconvex` | U (robust *assessment*) | Worst-case s-convex bounds on the basis risk of index-based (re)insurance contracts, with a catastrophe-model illustration. Assesses basis risk; does not design payouts | abs |
| `daron2014assessing` | U (uses climate scenarios) | Bayesian networks that bring observations and climate simulations into the pricing of a weather index product (Kolhapur, India). A sensitivity analysis of pricing; no robust optimisation | abs |
| `steinmann2023framework` (MAR-28) | U (uses climate scenarios) | Ex-post check of a chosen product under Knutson-scaled projections | MAR-28 |
| Huang, Ma, Guo & Gu (2026), arXiv 2608.15023 (MAR-28 "considered") | U | Wind-index contract for a power grid, chosen against a CVaR of energy not supplied over 80 scenarios. No worst case across scenario sets | abs |
| Tsekrekos, Papayiannis & Yannacopoulos (2026), ERES conference, doi:10.15396/eres2026_210 | U | DRO (Wasserstein) hedge ratios for real-estate portfolios hedged with index proxies. Financial hedging, not insurance | abs |
| Zenodo 2026 cluster: Kandil & El-Baz (doi:10.5281/zenodo.23543885); Mba Obame & Ondo Ella (…23544510); Mothibe et al. (…23545387); El Khattabi (…23545465) | U | DRO calibration of crop-yield estimators or premiums for "AI agriculture insurance". No payout design. Not peer-reviewed; the first abstract frames the work on rainfall but evaluates a temperature series. Not cited | abs |
| Fujii & Osaki (2020), SSRN, doi:10.2139/ssrn.3561406 | U | The title indicates optimal *demand* for index insurance under basis ambiguity, not payout design. Abstract not reachable | title |
| Diao, Weng & Zhang (2026), NAAJ, doi:10.1080/10920277.2026.2648974 | U | Expected-utility design that jointly selects weather variables and payout structure (Iowa soybeans). Not robust | abs |
| Lopez & Nkameni (2026), EAJ 16(2):297–328 | U | Demand and solvency conditions for index insurance, and a hybrid index–indemnity product. Not robust | abs |
| Assa (2026), arXiv 2608.24871 (NatPar) | U | A NatCat-style reporting standard for parametric contracts (EP curves, two-sided basis exceedance). Explicitly not an optimal-contract criterion | abs |
| Zhou, Dong, Fan & Wang (2026), Oper. Manag. Res. 19(3):45 | U | The title indicates incentive contracts around an index-based catastrophe cover in humanitarian logistics. Abstract behind a sign-in redirect | title |
| Enenkel et al. (2017), EGU abstract; Mazviona & Sølvsten (2025), *Front. Clim.*; Feleppa (2026), review | U | Climate change and index design, discussed qualitatively or reviewed. No robust optimisation (Enenkel: title only) | abs / title |
| Lemke, Guidotti & Franco (2025), LNCS; Chen, Escoto & Guidotti (2026), *Risks* | U | Cat-in-a-circle and cat-in-a-grid trigger design on a stochastic catalogue with cross-validation. Not robust (Lemke: title only) | abs / title |

### Observations for the owner (continuing O1–O6)

**O7. There is now direct prior art for robust design of parametric payouts.** Sadefo Kamdem (2026) designs parametric payouts that are robust to catastrophe-model ambiguity: a convex set of joint laws of need and index, under a worst-case asymmetric (expectile-type) basis-risk criterion that extends the Maier–Scherer line.
- *Differences from claim B, per the abstract only (full text not read):*
  - one contract for one policyholder;
  - analytic characterisations instead of an LP over explicit scenario event sets;
  - no tail functional such as CVaR is mentioned;
  - no joint multi-asset design;
  - no climate scenarios or vulnerability draws named as uncertainty sources;
  - no out-of-sample or price-of-robustness evaluation mentioned;
  - the empirical illustration is described as "specified", so it is unclear whether it was run.
- *Status:* an SSRN preprint whose Crossref record was created on 2026-10-18, a week before this search. It was found by G1–G3, O2, O3, O7, C1 and C4, and as a forward citation of both `steinmann2023framework` and `maier2026expectiles`. It is not peer-reviewed and may change.

**O8. R1's formulation has an insurance precedent on the indemnity side.** Asimit et al. (2017) write worst-case-scenario CVaR contract design over a finite set of candidate distributions as an LP. That is the indemnity counterpart of R1's epigraph LP (SPEC §6.5). Asimit et al. (2019) compare weighted-average and weighted-worst-case models over a finite model set. Together with Zhu & Fukushima (2009), this makes R1's technique standard *within insurance design*, not only in portfolio optimisation.

**O9. No hit designs index payouts against climate or hazard-catalogue scenarios as the uncertainty set.** Climate and catalogue uncertainty do appear elsewhere:
- as an ex-post test (Steinmann et al. 2023);
- in pricing assessments with climate model output (Daron & Stainforth 2014);
- in α-maxmin pricing over two hurricane catastrophe models (Dietz & Niehörster 2021);
- as ML-predicted emerging risk in robust premium setting (Bertsimas & Zeng 2024);
- as the motivation for indemnity layering under ambiguity (Birghila et al. 2022);
- as the abstract "convex set of catastrophe models" in Sadefo Kamdem (2026).

The OpenAlex query with catalogue terms (O4) could not be run, so this observation rests on O5, O8, W3 and the citation chains.

**O10. R2 sits closer to existing parametric work than R1 does.** Sadefo Kamdem includes Wasserstein sensitivity bounds for parametric payouts. A DRO variant (R2: a TV or χ² ball over year weights) would therefore be closer to existing parametric work than R1 over explicit hazard, vulnerability and climate event sets. Together with O2, this bears on D6 (MAR-29).

**O11. Robust assessment of basis risk exists; robust minimisation of basis risk for index contracts was found only in Sadefo Kamdem.** Lefèvre, Loisel & Montesinos (2021) bound the basis risk of index contracts under worst-case scenarios within a distribution class. They assess basis risk; they do not design payouts.

### Proposed claim B wording (owner decides: unchanged, narrowed or dropped)

**Proposal: narrowed.** O7 means "unchanged" would need a "first" claim that the search no longer supports.
- *Current (MAR-28):* "Robust payout design across hazard, vulnerability and climate scenarios", with "no robust or distributionally robust design of index-based payouts" in the sources checked.
- *Proposed:* "Scenario-robust (min–max) calibration of tail-objective step payouts for one owner's assets, jointly across hazard-catalogue, vulnerability and climate-scenario event sets, as a single LP, evaluated by leave-one-scenario-out tests and a price-of-robustness curve. Robust design of a single parametric contract under catastrophe-model ambiguity has been studied analytically (Sadefo Kamdem 2026), and the min–max LP has indemnity precedents (Asimit et al. 2017; Zhu & Fukushima 2009). The contribution is the computational, multi-asset and empirical setting over explicit event sets, not robust parametric design as such."
- *If dropped:* robustness would move into the evaluation (claim C) as robustness checks of the claim A design, and R2 would become optional (D6).
- *Either way:* the manuscript should cite Sadefo Kamdem (2026) and Asimit et al. (2017), and should re-check the preprint's status and content before submission.

### Verification log (MAR-75 entries)

| Key | Metadata checked against | Content read |
|---|---|---|
| `sadefokamdem2026robust` | Crossref (DOI; posted content, subtype preprint) | Abstract (Crossref). SSRN full text refused automated access (403) |
| `asimit2017robust` | Crossref (DOI) | Abstract (OpenAlex, publisher abstract) |
| `asimit2019finite` | Crossref (DOI) | Abstract (RePEc/IDEAS). ScienceDirect refused automated access (403) |
| `boonen2025wasserstein` | Crossref (DOI) | Abstract (OpenAlex, publisher abstract) |
| `jiang2026bregman` | arXiv API | Abstract |
| `birghila2022layering` | Crossref (DOI) | Abstract (Crossref) |
| `dietz2021pricing` | Crossref (DOI) | Abstract (Crossref) |
| `bertsimas2024catastrophe` | arXiv API | Abstract and model section (arXiv HTML v1) |
| `daron2014assessing` | Crossref (DOI) | Abstract (OpenAlex, publisher abstract) |
| `lefevre2021sconvex` | Crossref (DOI) | Abstract (OpenAlex, publisher abstract) |

Works classified from the title only (see the table) are not in `references.bib`.

**Limits of this search.**
- Scopus was not searched, Google Scholar only through G1–G3, and Semantic Scholar's keyword search not at all.
- O4 and C3 were not run.
- Sadefo Kamdem (2026) was read from its abstract only.

As in MAR-28, the absence of other hits is absence of evidence from a bounded search.

## Addendum (MAR-85): arXiv 2512.01623 checked against claim A

**Status: draft for owner review.** Prepared for [MAR-85](https://linear.app/marc-prinzing/issue/MAR-85/p-09-check-arxiv-251201623-weather-index-insurance-with-farmer-cvar) on 2026-10-25. The MAR-75 web search W7 turned up arXiv 2512.01623 and flagged it as bearing on claim A. This addendum classifies it. Nothing above this heading was changed. Every summary is a paraphrase. These are observations, not conclusions; the owner decides.

**Source and access (2026-10-25).** arXiv API record (`id_list=2512.01623`), the arXiv abstract page and the PDF of v1 (30 pages) were all reachable without sign-in. v1 of 2025-12-01 is the only version, with no journal reference. A Crossref title search (top 5 rows) found no published version. Read: abstract, sections 1–4 in full (introduction, formulation, algorithm, data), section 5.1.1 and the conclusion. The rest of section 5 was skimmed.

**Classification: related to claim A, not prior art for it.**

**`boonen2025monopoly`: Boonen, Li & Quan (2025), arXiv 2512.01623.**
- *What it does:* models the pricing of weather index insurance as a Bowley (leader–follower) game. The insurer picks a premium principle to maximise profit net of administrative costs: an expected-value loading θ, a two-parameter power distortion, or a general distortion pricing kernel. The farmer then picks a non-negative payoff I(X) of a weather-index matrix X to minimise a distortion risk measure of the hedged loss Y − I(X) + Π(I(X)) (their eq. 4). The farmer's measures are CVaR_α and the mix λ·E + (1−λ)·CVaR_α, with α = 0.8 and λ ∈ {0, 0.5} in the main runs.
- *Solver:* I(X) is a fully connected or convolutional neural network. The bilevel problem is solved by a penalised, first-order bilevel gradient method (value-gap penalty, subgradients via Danskin's theorem), with convergence results for a lower level that is convex but not strongly convex. The authors note that the CVaR lower-level objective is polyhedral and convex in the payoff values, but do not solve it as an LP.
- *Data:* Iowa county-level soybean yields (NASS, 1940–2023), detrended, with loss defined as the shortfall from the maximum observed yield. Monthly PRISM weather variables form the index matrix (the text says 7 indices × 12 months; Table 1 lists six variables). To enlarge the sample, the authors assume losses are homogeneous across time and space and pool 45 counties × 84 years into 3,780 county-years. Network size is chosen on a train/validation split (the split itself was not checked).
- *Findings reported:* stop-loss-shaped optimal payoffs under CVaR, smoother payoffs from CNNs than from fully connected networks, and higher equilibrium loadings and profits as the farmer's CVaR weight or the insurer's pricing flexibility grows.
- *What it does not do:* there is one payoff function for one representative farmer. The 45 counties are pooled as exchangeable observations, not insured as separate assets, so there are no per-asset payouts, no aggregate shortfall and no joint calibration. The premium is set by the insurer's pricing game, not by a budget constraint. The tail term is on the signed hedged loss, not on the one-sided shortfall (L − π)⁺. There is no LP.

**O12. Comparison with Fan, Tan & Zhang (2023).**
- *What they share:* a tail-risk design objective for one weather index contract on Midwest crop yields (Illinois corn there, Iowa soybeans here), taken on the hedged loss (for Fan et al. per the thesis; for this paper verified in eq. 4), solved by a non-LP search (annealing random search there, neural networks with bilevel gradient descent here). Boonen et al. cite Fan et al. as a tail-objective design method and present their algorithm as an alternative.
- *What is different:* Boonen et al. add an insurer who sets the price, so the premium is an equilibrium outcome rather than a given budget. Their objective includes the mixture λ·E + (1−λ)·CVaR, which has the same form as the paper's α·CVaR_β + (1−α)·E (with the weights swapped in name), but it is applied to the signed hedged loss. The MAR-28 entry for Fan et al. (from their abstract) records VaR, CVaR and EVaR as objectives, with no mean term. Boonen et al.'s payoff is a neural network of a weather matrix, not a capped step function.
- *Consequence for the reference list:* `fan2023tail` stays the closest reference for a tail objective in index design without a pricing game. `boonen2025monopoly` is a second instance of the same single-contract pattern, and the first source in this review, read in full text, whose design objective is a mean–CVaR mix.

**O13. A mean–CVaR mix has been used as an index-design objective; its one-sided, budgeted form differs.**
- *Tail part:* by O1, CVaR of the signed hedged loss and CVaR of U = (L − π)⁺ have the same minimisers at event level when the premium is fixed and the relevant quantile of L − π is non-negative.
- *Mean part:* on the signed hedged loss, E[Y − I + Π] = E[Y] + θ·E[I] under an expected-value premium. In Boonen et al.'s game, where the farmer picks I for a given θ, this term prices the loading. Under a fixed, binding budget, as in SPEC §6, a mean of the signed residual would be constant and have no effect. E[(L − π)⁺] does not reduce to a constant.
- *Implication:* a reader could still see "weighted CVaR plus mean" as already used for index payouts. This supports the MAR-28 proposal to rest claim A on the joint multi-asset scope and the exact LP, not on the form of the objective.

**Proposed claim A wording (owner decides).**
- *Proposal: unchanged.* Claim A's "Why it would be new" (no source calibrates distinct per-asset payouts jointly against an owner's aggregate tail shortfall) still holds for this paper.
- *Proposed addition to the closest-prior-work list in `positioning.md` (not made here):* "Boonen, Li & Quan (2025) design one index payoff against a farmer's λ·E + (1−λ)·CVaR of the hedged loss, inside a monopoly-pricing game, with neural-network payoffs and a bilevel gradient solver. Counties are pooled, not designed jointly."
- *Optional wording guard:* if the manuscript describes the objective, it could say that mean–CVaR mixes have been used as index-design objectives (Fan et al. 2023; Boonen et al. 2025), and that the contribution is the joint, budgeted, one-sided, annual-basis formulation as an exact LP.

**Verification log (MAR-85).**

| Key | Metadata checked against | Content read |
|---|---|---|
| `boonen2025monopoly` | arXiv API record and abstract page (v1 2025-12-01, q-fin.RM, no journal reference); Crossref title search found no published version | Full text v1: sections 1–4, 5.1.1 and 6 read; the rest of section 5 skimmed |

**Limits.** The arXiv version is a preprint and may change. Only the top five Crossref rows were screened for a published version. Fan et al. (2023) is still compared through the thesis's account of its objective, since its full text is paywalled.

## Addendum (MAR-99): `climada_petals.engine.cat_bonds` (petals 6.2.0) checked against claim A

**Status: draft for owner review.** Prepared for [MAR-99](https://linear.app/marc-prinzing/issue/MAR-99/p-09-check-climada-petals-enginecat-bonds-petals-620-against-claim-a) on 2026-10-25, ahead of the CLIMADA proposal (MAR-47). Nothing above this heading was changed. Every summary is a paraphrase. These are observations, not conclusions; the owner decides. File and line references are to `climada_petals/engine/cat_bonds/` at tag `v6.2.0`.

**Sources and access (2026-10-25).** All public and read without sign-in:
- the `climada_petals` repository at tag `v6.2.0` (commit `6ecd7af0`, 2026-06-15), cloned read-only outside this repository. Read: every `engine/cat_bonds/*.py` file, the markdown cells of the tutorial `doc/tutorial/climada_engine_CATBonds.ipynb`, and `CHANGELOG.md`;
- petals PR #186, through the GitHub REST API: opened 2025-11-03 by the module's author, merged 2026-06-01. All 20 conversation comments, 33 review comments and 14 reviews were scanned by keyword, and the matching ones were read;
- petals Discussion #184 (opened 2025-09-29), from its HTML page: the opening post only, since the page showed no replies;
- the Crossref record of the SSRN preprint that the tutorial names as the paper behind the module (doi:10.2139/ssrn.6030454), and the EGU25 abstract by the same group (doi:10.5194/egusphere-egu25-17829).

Not read: the preprint's full text (SSRN returned HTTP 403 to automated access) and the master's thesis the module started from. Discussion #184 says the module is based on its author's master's thesis, but two web searches found no public copy.

**Classification: related to claim A, not prior art for it.**

**`climadapetals2026catbonds` and `bergmuller2026multicountry`: CLIMADA Petals 6.2.0, `engine.cat_bonds`, and Bergmüller, Juhel, Wattin Håkansson, Elsener, Bresch & Kropf (2026), SSRN preprint.**
- *What it does:* designs and simulates parametric sovereign cat bonds.
  - *Index and payout:* a country's exposed area is split into subareas, by a grid or a given GeoDataFrame. A subarea's index is the mean or a percentile of hazard intensity over its centroids (`subarea_calculations.py` L151–208). Each subarea gets a payout that rises linearly between a lower and an upper trigger. The payout is capped at the smaller of the subarea's largest modelled damage and the principal (L269–275, L493–521). The two triggers per subarea are the decision variables.
  - *Bond terms:* attachment and exhaustion (the principal) are inputs, given as amounts, exposure shares or return periods (L93–149).
  - *Simulation:* bond losses are simulated over multi-year terms, with monthly timing. VaR and ES at 95 % and 99 % of annual bond losses are reported (`sng_bond_simulation.py` L118–181, `utils_cat_bonds.py` L5–33).
  - *Pricing:* a regression on expected loss (Chatoro et al.), a curve fitted to World Bank cat bonds, or a target Sharpe ratio (`premium_class.py` L49–230).
  - *Pooling:* several countries can share one multi-country bond, and a genetic algorithm can form the pools (`pooling_functions.py`, `mlt_bond_simulation.py`).
- *Q1. Objective and risk measure:*
  - *Payout design:* per subarea, the sum over events of the squared difference between modelled subarea damage and payout (`subarea_calculations.py` L244–278; the sum of squares is at L276–277). The code calls this basis risk. It is symmetric and event-based. The payout design has no tail functional.
  - *Bond metrics:* VaR and ES of annual bond losses are reported after the design.
  - *Pooling:* the objective is a risk-concentration ratio, the members' summed marginal ES in the pool's tail over the sum of their standalone ES. It uses α = 1 − 1/(number of simulated years) (`pooling_functions.py` L53–57, L173–214). The tutorial attributes this method to Ciullo et al. (2023, `ciullo2023pooling`).
- *Q2. Joint or independent:* independent. `_calibrate_payout_fcts` loops over subareas and runs one optimisation per subarea, each against that subarea's own damage column (L317–328).
  - *Before the fit:* the only link to the aggregate is a filter. Events whose total damage over all subareas is below the attachment get zero damage (L308–309).
  - *After the fit:* an event's subarea payouts are summed, capped at the principal, and set to zero below a minimum payout (L439–442).
  - No term of the fitted objective depends on another subarea's payout or on the aggregate shortfall.
- *Q3. Solver:* heuristic.
  - *Payout design:* per subarea, SciPy `minimize` with COBYLA, a derivative-free local method, over the two triggers. The start is the 30th and 60th percentiles of hazard intensity, with up to 100,000 iterations. On failure, fallback thresholds (the median and maximum of the index) are used and a warning is logged (L37–57, L322–342). The objective is piecewise in the triggers and not convex in general.
  - *Pooling:* a `pymoo` integer genetic algorithm (population 2,000), restarted `n_opt_rep` times (default 100), keeping the best result (`pooling_functions.py` L63–90). No random seed is passed.
  - *Pricing:* the Sharpe-target premium comes from `scipy.optimize.minimize` on a squared Sharpe gap (`premium_class.py` L157–230).
- *Q4. Budget or premium constraint:* none in the payout design.
  - The principal caps the payout, but it is an input, not a decision variable.
  - Premiums are computed after the design from the simulated losses and do not feed back into it.
  - The only constraint inside an optimisation is in pooling: a maximum total principal per pool, entered as the constraint value `G` (`pooling_functions.py` L304–392; the constraint is at L385–392).
  - A multi-country bond's required principal is the largest total payout of any simulated term (`mlt_bond_simulation.py` L527–554).
- *Q5. Owners:*
  - *Single-country bond:* one issuer (one sovereign) with several subareas. In our terms, one owner with several assets or clusters, each calibrated on its own. That is the shape of our individual scope, with a symmetric criterion.
  - *Multi-country bond:* several owners. It reuses each country's calibrated payouts unchanged (`mlt_bond_simulation.py` L49–56). Payouts are capped per country by that country's principal, and overall by the pool's principal (L196–240). The total premium is split by each country's share of expected annual loss (L342, L426–428).
  - *Pooling:* chooses which countries share a bond. It does not change payouts.
- *What it does not do:*
  - no tail functional and no one-sided shortfall in the payout design;
  - no joint calibration of the subarea payouts against the issuer's aggregate damage or shortfall;
  - no budget or premium constraint in the design;
  - no LP or other exact convex program;
  - no out-of-sample split: calibration and bond simulation use the same event set, and none was found in the module or the tutorial;
  - no design under scenario uncertainty.

**O14. `cat_bonds` is the closest software instance of one-owner, per-subarea payouts, but it calibrates them one subarea at a time.**
- *Overlap with claim A:* one issuer, several spatial units, a distinct payout per unit, all in CLIMADA. On distinct payouts per asset it is closer to claim A than `steinmann2023framework`, which shares one product across all sites.
- *Difference:*
  - The subarea payouts are fitted independently, each on its own squared error, by COBYLA.
  - The issuer's aggregate (the sum, capped at the principal) is applied after the fit and is not in the objective.
  - In our terms, the design is the individual scope with a symmetric event-level criterion and a capped linear payout, solved heuristically.
  - It does not cover claim A's joint, aggregate, tail, budgeted LP, or the cluster and portfolio scopes.
- *Tail measures and pooling:* ES enters only the choice of pool members (Ciullo et al.'s concentration ratio) and the reported bond metrics, not the payout design. The pools span several sovereign owners and share premiums by expected-loss share. That matches the existing note in `positioning.md` that pools involve several owners and need a risk-sharing rule.
- *Terms to keep apart in the manuscript:* in `cat_bonds`, "basis risk" means event-level squared error, and "pooling" means grouping countries into one bond, not joint payout design. Neither matches our use.
- *Consistency with MAR-47:* this fits the CLIMADA proposal's description of the planned module as complementary to `cat_bonds`. The planned module would sit at the trigger-and-payout fitting step (in `cat_bonds`: per subarea, squared error, COBYLA). Bond simulation, pricing and pooling would stay downstream.

**Proposed claim A wording (owner decides).**
- *Proposal: unchanged.* Claim A's "Why it is new" (no source calibrates distinct per-asset payouts jointly against an owner's aggregate tail shortfall) still holds for this module, as far as its code shows.
- *Proposed addition to the closest-prior-work list in `positioning.md` (not made here):* "The CLIMADA Petals `cat_bonds` module (2026; Bergmüller et al., 2026) gives each subarea of one sovereign issuer its own linear payout. It fits each payout separately by squared error (COBYLA), then sums and caps them. Countries are pooled by a genetic algorithm on an ES-based concentration ratio."
- *What the list would gain:*
  - a current, open, CLIMADA-native example of distinct payouts per spatial unit, which shows that this step alone is not new. What stays new is the joint fit against the aggregate tail shortfall, under one budget, as an exact LP;
  - a precise point of contact for the CLIMADA proposal (MAR-47).

**Verification log (MAR-99).**

| Key | Metadata checked against | Content read |
|---|---|---|
| `climadapetals2026catbonds` | Repository tag `v6.2.0` (commit `6ecd7af0`); `CHANGELOG.md` (release 2026-06-15, PR #186); `pyproject.toml` (GPL-3.0); PR #186 REST record (merged 2026-06-01). No release DOI found | Every `engine/cat_bonds/*.py` file in full; tutorial markdown cells; PR #186 comments scanned by keyword; Discussion #184 opening post |
| `bergmuller2026multicountry` | Crossref record for doi:10.2139/ssrn.6030454 (posted content, preprint, created 2026-01-06). Author's given name checked against the EGU25 abstract | Not read (SSRN HTTP 403). Only the tutorial's description of it and the EGU25 abstract |

**Limits.**
- The preprint and the thesis were not read. They may contain a joint or tail-based variant that the released code lacks. Every answer above rests on the code at `v6.2.0`.
- Later petals versions may differ. Re-check before the CLIMADA proposal and the manuscript go out (MAR-39, MAR-47).
- The preprint is not peer-reviewed.
