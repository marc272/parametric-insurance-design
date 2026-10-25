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
