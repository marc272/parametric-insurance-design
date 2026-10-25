# K-01: CLIMADA module proposal (draft for the owner)

- Issue: [MAR-47](https://linear.app/marc-prinzing/issue/MAR-47/k-01-open-a-maintainer-discussion-for-a-parametric-module) (Human). Spec: SPEC §8, CLIMADA K-01.
- Prepared by an agent on 2026-10-25 (the issue's "Agent may prepare" part). **Nothing has been posted or sent.** Marc Prinzing reviews, edits, posts and holds the conversation.
- Feedback goes to [`docs/adr/climada-module.md`](../adr/climada-module.md), the input to K-02.

Contents:

1. [What changed since the issue was written](#1-what-changed-since-the-issue-was-written)
2. [Proposal text, ready to paste](#2-proposal-text-ready-to-paste)
3. [API sketch](#3-api-sketch)
4. [Decisions for Marc](#4-decisions-for-marc)
5. [What the maintainers are asked](#5-what-the-maintainers-are-asked)
6. [Publication-rule check](#6-publication-rule-check)
7. [Sources checked](#7-sources-checked)

## 1. What changed since the issue was written

The issue's motivation says there is no maintained parametric module in CLIMADA. That is no longer quite true:

- **`climada_petals.engine.cat_bonds`** was merged on 2026-06-01 ([PR #186](https://github.com/CLIMADA-project/climada_petals/pull/186)) and released in petals 6.2.0 (2026-06-15). It simulates **parametric sovereign cat bonds**:
  - it splits a country into subareas and uses the mean or a percentile of hazard intensity per subarea as the index;
  - per subarea, it fits a linear payout between a lower and an upper trigger by minimising the squared difference between damage and payout (`scipy.optimize.minimize`, COBYLA);
  - it groups countries into pools with a genetic algorithm (`pymoo`, added as a petals dependency in 6.2.0);
  - it also prices the bonds.
- It started from a master's thesis and was announced in a petals Discussion ([#184](https://github.com/CLIMADA-project/climada_petals/discussions/184), "Ideas" category). That discussion got no written replies. The PR was then reviewed on GitHub by `chahank` and `spjuhel` over about seven months. They asked for a hazard-agnostic tutorial, data from the CLIMADA Data API, probabilistic rather than historical tracks, and correct impact functions per region.
- Steinmann et al. (2023)'s code is in `climada_papers/archive/202303_parametric_insurance_framework`. This confirms the issue: it is archived and not a module.

Consequence: the proposal now describes our module as **complementary to `cat_bonds`**. Ours covers a different product: asset-level index cover for one owner, step payouts, and calibration as a linear program with a tail objective. The proposal asks how the two modules should relate. Our motivation is not "nothing exists".

## 2. Proposal text, ready to paste

Suggested place: GitHub Discussions on `CLIMADA-project/climada_petals`, category **Ideas** (as #184). Alternatives are listed under decision D6. The text below is about 650 words, the questions included. Copy everything between the two markers from the raw file.

<!-- BEGIN PASTE: title -->
Proposal: a module for parametric insurance design (index, step payout, calibration, basis-risk metrics)
<!-- END PASTE: title -->

<!-- BEGIN PASTE: body -->
Hi CLIMADA team,

I'd like to contribute a module for designing parametric (index-based) insurance covers with CLIMADA. As the contribution guide suggests, I'd like to agree on the design with you before writing it.

**Motivation**

CLIMADA already provides what a parametric design needs:

- a hazard to build the index from;
- exposures;
- modelled losses to measure basis risk against.

Steinmann et al. (2023, *Environment Systems and Decisions*, [doi:10.1007/s10669-023-09934-x](https://doi.org/10.1007/s10669-023-09934-x)) showed how to design a cover this way. Their code is archived in `climada_papers` (`archive/202303_parametric_insurance_framework`) and is not a maintained module. The new `engine.cat_bonds` module (#186) covers sovereign cat bonds: payout functions per subarea, and pooling across countries. What is still missing is the asset-level case. Here one risk owner (a company, a municipality or a government) holds several assets, and each asset or group of assets gets its own index and payout.

**What the module would do**

- **Index builders:** hazard intensity at an exposure point's centroid; cat-in-a-circle from `TCTracks` (maximum Saffir–Simpson category within radius r, as in Steinmann et al.); a value-weighted mean index over a group of exposure points.
- **Step payout:** a monotone, capped step function of the index, with breakpoints between an attachment and a limit.
- **Calibration:** fits the payout levels of all assets at once, under one premium budget. The objective is one of:
  - mean squared error;
  - expected uncovered loss E[U], with U = (L − payout)⁺;
  - a weighted CVaR of the uncovered loss, α·CVaR_β(U) + (1 − α)·E[U].

  With the Rockafellar–Uryasev reformulation, the E[U] and CVaR versions are linear programs.
- **Options:** one problem per asset, or one joint problem on the owner's total loss. Pricing is a pure premium, or a cost-of-capital load, which keeps the problem linear.
- **Basis-risk metrics:**
  - the metrics: E[U], VaR and CVaR of U, RMSE, the payout-to-loss ratio and the correlation;
  - on a per-event or per-year basis;
  - with train/test splits by year.

Inputs and outputs are CLIMADA objects:

- `Hazard` or `TCTracks`, and `Exposures`, for the index;
- an `Impact` with `imp_mat` as the loss to cover;
- payouts returned as an `Impact`, so that `calc_freq_curve`, `impact_per_year` and the plotting tools work on them.

A short sketch is below.

**Where it comes from**

The method comes from my master's thesis (TUM, 2026). I am turning it into a tested Python library ([marc272/parametric-insurance-design](https://github.com/marc272/parametric-insurance-design)). The library already has a CLIMADA pipeline for tropical-cyclone event sets. The petals module would port the hazard-agnostic parts under petals' GPLv3, with:

- unit and integration tests;
- pylint-clean code;
- a tutorial on open data (LitPop and synthetic tracks);

and come as a PR to `develop`.

**Proposed location and dependencies**

- **Location:** a new subpackage, `climada_petals.engine.parametric`, next to `cat_bonds`. Where the two overlap (an index per area, payout-versus-damage tables), I'm happy to share or align code.
- **Solver:** the linear objectives can use SciPy's HiGHS (`scipy.optimize.linprog(method="highs")`), so no new dependency is needed. Only the MSE objective is a quadratic program. It could use an optional dependency (for example cvxpy), or be left out.

**Questions**

1. Is a new `climada_petals.engine.parametric` the right place? Or would you rather extend or share code with `engine.cat_bonds`, or see this as a separate package?
2. Would you prefer SciPy/HiGHS (no new dependency) to cvxpy? Is an optional extra acceptable for the quadratic MSE objective?
3. Representation: I'd return payouts as an `Impact` and keep the index in a small table aligned with the `Hazard` events. Or would you prefer Steinmann et al.'s style, with the index as a `Hazard` and the payout as an `ImpactFuncSet`?
4. Annual metrics need the simulation year of each event. What is the recommended way to get it for probabilistic sets (`Hazard.date` versus `frequency`)? I'm thinking of synthetic or STORM tracks, where `cat_bonds` reassigns dates.
5. For the tutorial: is LitPop with synthetic tracks the right open dataset, ideally loaded from the Data API?

<details>
<summary>API sketch (proposal only, nothing implemented yet)</summary>

```python
from climada.engine import ImpactCalc
from climada.entity import Exposures, ImpactFuncSet, ImpfTropCyclone
from climada.hazard import Centroids, TCTracks, TropCyclone
from climada_petals.engine import parametric as pm

exp = Exposures(lat=lat, lon=lon, value=value)  # one point per insured asset
tracks = TCTracks.from_ibtracs_netcdf(basin="NA", year_range=(1980, 2020))
tracks.equal_timestep(1)
tracks.calc_perturbed_trajectories(nb_synth_tracks=9)
haz = TropCyclone.from_tracks(tracks, centroids=Centroids.from_exposures(exp))
exp.gdf["impf_TC"] = 1
imp = ImpactCalc(exp, ImpactFuncSet([ImpfTropCyclone.from_emanuel_usa()]), haz).impact(
    save_mat=True
)

index = pm.ParametricIndex.from_cat_in_circle(tracks, exp, hazard=haz, radius_km=50)
train, test = pm.split_years(index, train_fraction=0.7)

cover = pm.calibrate(
    index,
    imp,
    payout=pm.StepPayout(attachment=1, limit=5, n_steps=5),
    objective=pm.WeightedCVaR(alpha=0.5, beta=0.99),
    scope="portfolio",
    budget=1.0,
    basis="annual",
    years=train,
)
payout = cover.payout_impact(index)  # a climada Impact
pm.basis_risk(imp, payout, basis="annual", beta=0.99, years=test)  # a DataFrame
```

</details>

Thanks for reading. I'd be glad to present this at a developers' call too.

Marc
<!-- END PASTE: body -->

## 3. API sketch

**This is a sketch for the discussion. Nothing in it is implemented, and every name is open.** It follows CLIMADA conventions as far as we checked them (§7):

- inputs and outputs are CLIMADA objects;
- alternative constructors are named `from_*`;
- no class inherits from an external library;
- no function takes more than five parameters without keywords;
- logging goes through the petals `LOGGER`.

It is hazard-agnostic: only `from_cat_in_circle` is specific to tropical cyclones. The CLIMADA calls in the example match the current `climada_python` sources (`Exposures(lat=, lon=, value=)`, `Centroids.from_exposures`, `TCTracks.from_ibtracs_netcdf`, `TCTracks.calc_perturbed_trajectories`, `Impact.calc_freq_curve`, `Impact.impact_per_year`).

```python
# climada_petals/engine/parametric/  (sketch)
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from climada.engine import Impact
from climada.entity import Exposures
from climada.hazard import Hazard, TCTracks

Basis = Literal["annual", "event"]
Scope = Literal["individual", "portfolio"]


class ParametricIndex:
    """Index values per event and insured unit, aligned with a Hazard's events.

    A unit is one exposure point or, with ``group_by``, one group of points
    (one payout function per unit).

    Attributes
    ----------
    values : np.ndarray            # (n_events, n_units)
    event_id, event_name : np.ndarray   # as in the Hazard
    frequency : np.ndarray         # events per year, as in the Hazard
    date : np.ndarray              # ordinal dates, used for the year of each event
    unit_id : np.ndarray           # exposure index labels or group labels
    unit : str                     # e.g. "m/s" or "Saffir-Simpson category"
    definition : str               # human-readable index definition
    """

    @classmethod
    def from_hazard(
        cls, hazard: Hazard, exposures: Exposures, *, group_by: str | None = None
    ) -> "ParametricIndex":
        """Intensity at each exposure point's assigned centroid; with
        ``group_by`` (a column of ``exposures.gdf``), the value-weighted mean
        over each group."""

    @classmethod
    def from_cat_in_circle(
        cls,
        tracks: TCTracks,
        exposures: Exposures,
        *,
        hazard: Hazard,
        radius_km: float,
        group_by: str | None = None,
    ) -> "ParametricIndex":
        """Maximum Saffir-Simpson category of each track within ``radius_km``
        of each exposure point, matched to ``hazard`` events by event name."""

    def years(self) -> np.ndarray:
        """Simulation year of each event (see question 4)."""


def split_years(
    index: ParametricIndex, *, train_fraction: float = 0.7
) -> tuple[np.ndarray, np.ndarray]:
    """Contiguous blocks of years for training and testing. All the events of a
    year stay in the same block."""


@dataclass(frozen=True)
class StepPayout:
    """Monotone, capped step payout: level k is paid when the index falls in
    bin k. The bins are uniform on [attachment, limit]; above the limit the top
    level is paid. The cap per unit defaults to the unit's maximum loss."""

    attachment: float
    limit: float
    n_steps: int


@dataclass(frozen=True)
class MeanSquaredError: ...  # QP: needs a QP solver (decision D2)


@dataclass(frozen=True)
class ExpectedUncovered: ...  # E[U], LP


@dataclass(frozen=True)
class WeightedCVaR:  # alpha * CVaR_beta(U) + (1 - alpha) * E[U], LP
    alpha: float = 0.5
    beta: float = 0.99


@dataclass(frozen=True)
class PurePremium: ...  # premium = E[payout]


@dataclass(frozen=True)
class CostOfCapitalLoad:  # (1 - rate) * E[payout] + rate * CVaR_q(payout), LP
    rate: float = 0.08
    q: float = 0.99


@dataclass
class ParametricCover:
    """A calibrated cover."""

    payout: StepPayout
    levels: pd.DataFrame  # unit_id, step, lower, upper, value (currency)
    premium: float
    objective_value: float
    solver: dict  # status, solver name, iterations, time

    def payout_impact(self, index: ParametricIndex) -> Impact:
        """Payouts as a CLIMADA Impact: one column per unit in ``imp_mat``,
        ``at_event``, ``frequency`` and ``date`` taken from the index."""


def calibrate(
    index: ParametricIndex,
    impact: Impact,
    *,
    payout: StepPayout,
    objective: MeanSquaredError | ExpectedUncovered | WeightedCVaR,
    scope: Scope = "individual",
    pricing: PurePremium | CostOfCapitalLoad = PurePremium(),
    budget: float | None = None,
    basis: Basis = "annual",
    years: np.ndarray | None = None,
) -> ParametricCover:
    """Fit the payout levels of every unit at once.

    ``impact`` must hold ``imp_mat`` (``save_mat=True``). Its columns are
    summed to the index's units. ``budget`` is kappa in
    premium <= kappa * E[loss]. ``scope="portfolio"`` puts the objective on
    the summed loss and payout of all units; ``"individual"`` solves one
    problem per unit. An infeasible or failed solve raises an error; it never
    falls back silently."""


def basis_risk(
    impact: Impact,
    payout: Impact,
    *,
    basis: Basis = "annual",
    beta: float = 0.99,
    years: np.ndarray | None = None,
) -> pd.DataFrame:
    """E[U], VaR_beta(U), CVaR_beta(U), RMSE, E[payout]/E[loss] and the
    correlation, per unit and for the portfolio."""
```

How the sketch maps to the core library (`packages/core`, ADR 0002), to guide the K-02 design ADR and the K-03 port:

| Sketch | Core module | Port notes |
|---|---|---|
| `ParametricIndex.from_hazard` | `index.py` (`PointIndex`, `ValueWeightedIndex`), CLIMADA adapter pipeline | The adapter's `CentroidWindIndex` (`hooks.py`) is the reference |
| `ParametricIndex.from_cat_in_circle` | MAR-26 (F-12) `IndexBuilder` in the adapter | Not built yet |
| `split_years` | `splits.py` | Year blocks; draws never cross blocks |
| `StepPayout` | `payout.py` | Same parameters; the cap default as in `problem.build_context` |
| `MeanSquaredError`, `ExpectedUncovered`, `WeightedCVaR` | `objectives.py` | Core builds cvxpy expressions; petals would assemble sparse LP matrices for HiGHS if D2 = scipy |
| `PurePremium`, `CostOfCapitalLoad`, `budget` | `pricing.py`, `constraints.py` | |
| `scope` | `scopes.py` | Cluster scope = `group_by` plus `"portfolio"`. Ward clustering is not proposed for petals |
| `basis` | `basis.py` | `"annual"` needs F-10 (MAR-24); `event_conditional` (thesis parity only) is not proposed for petals |
| `calibrate` → `ParametricCover` | `problem.py`, `solve.py` | Scaling and solver fallbacks as in the core |
| `basis_risk` | `evaluate.py` | |

Out of scope for the module, per SPEC §8: CRC and VELO code and data, the robust-design research code (unless the maintainers ask for it), and the paper experiments.

## 4. Decisions for Marc

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | **Where the module lives** | (a) new `climada_petals.engine.parametric`; (b) extend `engine.cat_bonds`; (c) separate package, e.g. our GPL `parametric-insurance-design-climada` published on PyPI and conda-forge; (d) thin petals wrapper that depends on our BSD core from PyPI | **(a)**, and ask (question 1). It matches SPEC §8 (K-03 "in a `climada_petals` fork") and the precedent of `cat_bonds`. (b) mixes two products with different calibration methods. (d) would bring our core's pins (cvxpy, pydantic, pyarrow) into petals, which the dependency rule ("as few as possible") argues against. (c) is the fallback if they decline |
| D2 | **Solver dependency** | scipy HiGHS (`linprog(method="highs")`), which needs no new dependency; cvxpy as a required dependency; cvxpy as an optional extra | **scipy HiGHS for the LP objectives**, and ask about an optional extra for MSE (question 2). scipy is already in every CLIMADA env (CLIMADA 6.1 pins scipy 1.15). cvxpy is not a CLIMADA or petals dependency, and in the CLIMADA env (numpy 1.26) it resolves to 1.7.x, which has no bundled HiGHS (ADR 0002). Cost: K-03 builds the sparse LP matrices itself instead of reusing the core's cvxpy assembly, so it needs a parity test against the core. MSE is a QP that scipy's `linprog` can't solve: use the optional extra, scipy's SLSQP for small problems, or leave MSE out of the first version |
| D3 | **Licence compatibility** | — | **No blocker.** Checked from the primary source on 2026-10-25: petals' `LICENSE` is the GPL v3 text; `pyproject.toml` says "GNU General Public License v3 (GPLv3)"; the file headers say "version 3", with no "or later" clause, and "Copyright (C) 2017 ETH Zurich, CLIMADA contributors listed in AUTHORS". Our adapter (GPL-3.0-or-later) and core (BSD-3-Clause) can both be combined into GPLv3-only code (ADR 0001). Ported code would carry the petals header, and you would be listed in `AUTHORS.md`. As copyright holder, you keep the right to license the core as BSD. The contribution guide mentions no CLA. Accept the petals header convention. Optionally confirm in the thread that nothing else is needed |
| D4 | **Mention the paper?** | Mention the thesis only; also say "a paper is in preparation"; say nothing about either | **Thesis only, as drafted. Leave the paper out.** The module doesn't depend on the paper (SPEC §8). Mentioning it invites questions about results that we can't answer before C1. The draft makes no performance claim (§6). If you do mention it, use one neutral sentence ("a paper on the method is in preparation"), with no results or timeline |
| D5 | **Contact the ETH Weather and Climate Risks group?** | Discussion only; discussion plus a request to present at the monthly CLIMADA developers' call; also email the lead developers; also @-mention reviewers in the post | **Post the discussion first, then ask to present at a developers' call, linking the discussion.** The contribution guide calls the monthly call "a good place to start a personal discussion", and you contact the lead developers to join. The comparable discussion #184 got no written reply, while its PR was reviewed by `chahank` and `spjuhel`. So a discussion alone may not produce feedback. Whether to @-mention them is your call; the draft does not |
| D6 | **Where to post** | petals Discussions ("Ideas"); `climada_python` Discussions ("General", label "new module"); an issue on petals | **petals Discussions, "Ideas"**. The module goes to petals, and #184 is the direct precedent. The contribution guide links `climada_python` Discussions in general, and a recent new-module discussion is there ("Option Appraisal Module Organization", 2026-05-21, label "new module"). If there is no reply within a few weeks, cross-post a link there |
| D7 | **How to describe the relation to `cat_bonds`** | Complementary (as drafted); propose a merge or shared base; don't mention it | **Complementary, with an offer to share code where they overlap**, as drafted. Not mentioning it would look like we hadn't looked |
| D8 | **Link the public repository and the thesis?** | Link the repository (as drafted) and the thesis PDF if it's public; link neither | **Link the repository.** Add a link to the thesis only if it is public. The draft cites it as "my master's thesis (TUM, 2026)" |

## 5. What the maintainers are asked

These are the five questions in the post (§2). Each answer goes to `docs/adr/climada-module.md`.

1. **Location:** a new `climada_petals.engine.parametric`, an extension of or shared code with `engine.cat_bonds`, or a separate package?
2. **Solver dependency:** SciPy/HiGHS (no new dependency) or cvxpy? Is an optional extra acceptable for the quadratic MSE objective?
3. **Representation:** payouts as an `Impact`, with the index in a table aligned with the `Hazard` events? Or Steinmann et al.'s style, with the index as a `Hazard` and the payout as an `ImpactFuncSet`?
4. **Simulation years:** the recommended way to get each event's year in probabilistic sets (`Hazard.date` versus `frequency`), for annual metrics. Synthetic and STORM tracks are the case in point.
5. **Tutorial data:** is LitPop with synthetic tracks right, and should it be loaded from the Data API?

## 6. Publication-rule check

Until checkpoint C1 (MAR-29) is Done (AGENTS.md, SPEC §1), the post must stay within these limits. The draft:

- presents the method and the tool only;
- shows **no result numbers**. The numbers in the sketch (`radius_km=50`, `alpha=0.5`, `beta=0.99`, `budget=1.0`, steps) are example arguments, not results;
- makes **no claim that tail optimisation performs better** than MSE or E[U] designs. The weighted CVaR is listed as one objective among three;
- makes **no novelty claim**. It describes the gap (an asset-level module for one owner) as something missing from CLIMADA, not from the literature. It credits Steinmann et al. (2023) for the cat-in-a-circle index and the CLIMADA design approach. This is consistent with `research/lit/positioning.md` (claim C) and `research/lit/notes.md` (O3: "present it as realism, not novelty").

If you edit the text, keep these limits.

## 7. Sources checked

All read-only, on 2026-10-25. Nothing was posted, commented on or starred.

| Source | What it gave |
|---|---|
| `CLIMADA-project/climada_petals` (GitHub API): `LICENSE`, `pyproject.toml`, `CHANGELOG.md`, `climada_petals/engine/cat_bonds/*` | Licence (D3); dependencies (`pymoo` added in 6.2.0; no cvxpy); the `cat_bonds` design (§1) |
| petals [PR #186](https://github.com/CLIMADA-project/climada_petals/pull/186) and its comments | What the reviewers asked for (§1); dependency handling (`pymoo` was added to `pyproject.toml` during review) |
| petals [Discussions](https://github.com/CLIMADA-project/climada_petals/discussions) and [#184](https://github.com/CLIMADA-project/climada_petals/discussions/184) | Categories (Announcements, General, Ideas, Polls, Q&A, Show and tell); the precedent and its lack of replies (D5, D6) |
| `climada_python` [CONTRIBUTING.md](https://github.com/CLIMADA-project/climada_python/blob/main/CONTRIBUTING.md) and [Discussions](https://github.com/CLIMADA-project/climada_python/discussions) | "talk to us first" for new modules; the developers' call; PRs to `develop`; `.pylintrc`; `AUTHORS.md` |
| [CLIMADA conventions guide](https://climada-python.readthedocs.io/en/latest/development/Guide_CLIMADA_conventions.html) | Dependency rule ("as few as possible"; new packages need an admin's permission and an issue); no inheritance from external classes; refactor methods with more than 5 parameters |
| `climada_python` sources (`Exposures.__init__`, `Centroids.from_exposures`, `TCTracks.from_ibtracs_netcdf`, `Impact.impact_per_year`, `Impact.calc_freq_curve`) and `pyproject.toml` | The CLIMADA calls in the sketch; core dependencies (no cvxpy) |
| `CLIMADA-project/climada_papers` (`archive/`) | Steinmann et al.'s code is in `archive/202303_parametric_insurance_framework` |

Not verified:

- The CLIMADA "Python Dos and Don'ts" and "Git development" guides were not reread beyond the contribution guide.
- The sketch has not been run. It is not code, and the petals module doesn't exist yet.
- Whether `TropCyclone.from_tracks` with perturbed tracks sets `frequency` to 1 / (years × (1 + synthetic tracks per track)) was not checked. Question 4 covers it.
- Whether the thesis PDF is public (D8).
