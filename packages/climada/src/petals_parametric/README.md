# petals_parametric: a prototype parametric insurance module for CLIMADA

A prototype of a `climada_petals.engine.parametric` module. It designs index-based (parametric) covers for the sites of one risk owner, on CLIMADA's own objects: `Hazard`, `TCTracks`, `Exposures` and `Impact`. It is not part of `climada_petals` or of any release, and its design may still change.

It is laid out like the future petals subpackage, so that moving it there is a copy (see "Moving it into climada_petals" below). It never imports this repository's other packages: only the standard library, CLIMADA, numpy, scipy and pandas, plus cvxpy for one optional objective.

## What it does

A cover pays a step function of a hazard index at each insured site (a *unit*: one exposure point). The calibration chooses the payout levels. It carries two ideas, usable on their own or together:

- **A tail-risk objective.** The uncovered loss of an outcome is `U = sum over its events of (loss - payout)^+`. `WeightedCVaR(alpha, beta)` minimises `alpha * CVaR_beta(U) + (1 - alpha) * E[U]`: alpha weights the CVaR term, so `alpha = 0` is the expected uncovered loss and `alpha = 1` its CVaR alone. With the Rockafellar–Uryasev form of the CVaR the design problem is a linear program. `ExpectedUncovered()` and `MeanSquaredError()` fill the same slot.
- **The calibration scope.** `scope="individual"` solves one design problem per site, each with its own objective and premium budget. `scope="portfolio"` solves one joint problem for the owner: each site keeps its own payout function, but the objective and the budget are on the owner's total loss and payout, so within an event an over-payment at one site can offset a shortfall at another.
- **The combination:** the weighted-CVaR objective with `scope="portfolio"`, a tail objective on the owner's total uncovered loss.

These are methods. Which one suits a cover depends on the owner and the data; nothing here says that one gives better cover than another.

Also:

- **Index builders:** `ParametricIndex.from_hazard` (the hazard intensity at each site's centroid) and `ParametricIndex.from_cat_in_circle` (the highest Saffir–Simpson category that a storm's track reaches within `radius_km` of the site, from `TCTracks`, as in Steinmann et al. 2023).
- **Step payout:** `StepPayout(attachment, limit, n_steps)`, monotone and capped at each site's largest loss. **Nothing is paid below the attachment** (`below_attachment="zero"`, the default), so a hazard set may leave out loss-free events below it without changing the design. `"first_bin"`, which pays the first level there, exists to compare with older designs.
- **Pricing and budget:** `PurePremium()` or `CostOfCapitalLoad(rate, q)`, `(1 - rate) E[payout] + rate CVaR_q(payout)`, which keeps the problem linear; the budget is `premium <= budget * E[loss]`.
- **Basis:** `basis="annual"` makes each simulation year an outcome (the events of a year are summed), so `beta = 0.99` is the 100-year level. `basis="event"` makes each event an outcome.
- **Metrics:** `basis_risk` (expected, VaR and CVaR of the uncovered loss, RMSE, payout-to-loss ratio, correlation and premium, per site and for the total), usually on test years from `split_years`. `ParametricCover.payout_impact` returns the payouts as a CLIMADA `Impact`.

## Usage on CLIMADA objects

First the CLIMADA part: sites, tracks, the wind hazard at the sites and the impact. This block downloads IBTrACS, so it is not run in this repository's CI.

<!-- example: climada -->
```python
import numpy as np
from climada.engine import ImpactCalc
from climada.entity import Exposures, ImpactFuncSet, ImpfTropCyclone
from climada.hazard import Centroids, TCTracks, TropCyclone

# One exposure point per insured site (latitude, longitude, value in USD).
exposures = Exposures(
    lat=np.array([25.76, 25.79, 25.95]),
    lon=np.array([-80.19, -80.13, -80.14]),
    value=np.array([1e9, 2e9, 5e8]),
)
exposures.gdf["impf_TC"] = 1

# Historical tracks: one event per storm, frequency 1 / (number of years).
tracks = TCTracks.from_ibtracs_netcdf(
    provider="usa", basin="NA", year_range=(1980, 2023)
)
tracks.equal_timestep(time_step_h=1)
hazard = TropCyclone.from_tracks(tracks, centroids=Centroids.from_exposures(exposures))
impfset = ImpactFuncSet([ImpfTropCyclone.from_emanuel_usa()])
impact = ImpactCalc(exposures, impfset, hazard).impact(save_mat=True)
```

Then the covers. This block is run in CI (`tests/test_petals_parametric_readme.py`) on small synthetic `tracks`, `hazard`, `exposures` and `impact`:

<!-- example: design -->
```python
import petals_parametric as pm

# The index: the cat-in-a-circle category within 50 km of each site, aligned
# with the hazard's events. ParametricIndex.from_hazard(hazard, exposures)
# would use the wind at each site instead.
index = pm.ParametricIndex.from_cat_in_circle(
    tracks, exposures, hazard=hazard, radius_km=50
)
train, test = pm.split_years(index, train_fraction=0.7)

# Categories 1 to 5 each pay their own level; category 0 pays nothing.
payout = pm.StepPayout(attachment=1, limit=6, n_steps=5)
tail_objective = pm.WeightedCVaR(alpha=0.9, beta=0.95)

# The tail objective, one design problem per site.
tail = pm.calibrate(
    index,
    impact,
    payout=payout,
    objective=tail_objective,
    basis="annual",
    scope="individual",
    budget=1.0,
    years=train,
)
# Joint calibration with the expected uncovered loss.
joint = pm.calibrate(
    index,
    impact,
    payout=payout,
    objective=pm.ExpectedUncovered(),
    basis="annual",
    scope="portfolio",
    budget=1.0,
    years=train,
)
# The combination: the tail objective on the owner's total.
combined = pm.calibrate(
    index,
    impact,
    payout=payout,
    objective=tail_objective,
    basis="annual",
    scope="portfolio",
    budget=1.0,
    years=train,
)

print(combined.summary())  # objective value, premium, budget and solver per problem
print(combined.levels_frame())  # the payout level of each site and step
metrics = pm.basis_risk(index, impact, combined, beta=0.95, years=test)
payouts = combined.payout_impact(index, impact)  # a CLIMADA Impact
```

Every number such a run prints depends on its setup: the sites and their values, the hazard set and its years, the index (here cat-in-a-circle at 50 km), the impact function, the basis (annual), the pricing (pure premium), the budget (1.0) and the split (the first 70 % of the years for calibration). State them next to any result.

## Things to know

- **Simulation years.** The annual basis needs each event's simulation year, and every year of the hazard set, including the years without events. The index builders take them in three parts:
  - **each event's year**, `event_year`: by default the calendar year of `hazard.date` (`"date"`), as `TropCyclone.from_tracks` sets it for historical tracks. `"event_name"` (opt-in) reads it from event names of the form `<prefix>_<year>_<number>`, such as `NA_9999_0`, and raises on a name of any other form. Or pass one year per event;
  - **the number of years** `N`, `n_years`: by default `1 / frequency`, which must then be the same for every event;
  - **the first year**, `first_year`: by default the first event's year, but only if the events' years run over exactly `N` years. Otherwise the years without events could lie before the first event or after the last one, so the builders raise rather than guess.

  `years`, the list of all the years, can replace `n_years` and `first_year`. On the annual basis every event's frequency must be one over the number of years; otherwise calibration raises.

  A CLIMADA date holds the calendar years 1 to 9999 only, and the tracks of a synthetic catalogue often all start on one date, so the dates may not carry the years. For IRIS, which numbers its 10,000 years from 0, read the years from the event names and state the first year:

  ```python
  index = pm.ParametricIndex.from_hazard(
      hazard, exposures, event_year="event_name", first_year=0
  )
  ```

  An ensemble of perturbed tracks (`calc_perturbed_trajectories`) has frequency `1 / (N * ensemble size)`; its members share their parent's date, and their names (`<parent>_gen<m>`) give no year. Pass `event_year` as an array, giving member `m` of year `y` the year `y + m * N`, and `first_year`.
- **Per-site levels of a portfolio cover are not unique.** The joint objective sees only each event's total payout, so other splits across the sites are optimal too. A portfolio cover holds the one split the solver returned; `basis_risk` marks its per-site rows `split_identified = False`.
- **Budgets per scope.** In the individual scope every site has its own budget, `premium_j <= budget * E[L_j]`; in the portfolio scope the total premium is bounded by `budget * E[sum_j L_j]`. Under the pure premium both scopes spend the same total budget.
- **Degenerate tails.** When `beta` is at most the probability of the outcomes without loss, the weighted-CVaR objective has the same minimisers as `E[U]`. `calibrate` records this as `degenerate_tail` in each problem's diagnostics and logs a warning; it also flags a `1 - beta` smaller than one outcome's probability (`tail_within_one_outcome`).
- **No silent failures.** Mismatched inputs (an `Impact` of other events or sites, frequencies that do not fit the basis) raise `ParametricInputError`; an unsolved problem raises `CalibrationError`. Nothing is skipped.

## Solvers and dependencies

- `ExpectedUncovered` and `WeightedCVaR` are linear programs, solved with scipy's HiGHS (`scipy.optimize.linprog(method="highs")`): no dependency beyond CLIMADA's own.
- `MeanSquaredError` is a quadratic program, which scipy cannot solve. It uses cvxpy and the Clarabel solver that comes with it, imported only for this objective. Without cvxpy, it raises `MissingDependencyError`; the other objectives work.
- Loss-free events get no shortfall variable, so the program grows with the events that have loss, not with the whole hazard set. This matters with scipy 1.15 (CLIMADA 6.1's pin): after HiGHS returns, its `linprog` loops over the variables' basis statuses in Python, which takes time that grows with the square of the number of variables.

## Moving it into climada_petals

The folder maps one to one onto `climada_petals/engine/parametric/`:

| Here | In petals |
|---|---|
| `petals_parametric/*.py` | `climada_petals/engine/parametric/*.py` |
| `petals_parametric/test/*.py` | `climada_petals/engine/parametric/test/*.py` (unittest classes, as petals' tests) |
| `README.md` (this file) | the seed of the module's tutorial |
| `ruff.toml` | not moved: it is this repository's import-isolation rule |

Steps:

1. Copy the files; replace `petals_parametric` with `climada_petals.engine.parametric` in the tests (the package itself uses relative imports).
2. Put petals' GPL v3 licence header at the top of every file.
3. Declare cvxpy as an optional dependency in petals' `pyproject.toml`, e.g. `parametric = ["cvxpy>=1.6"]`.
4. Run petals' pylint (`.pylintrc`) and tests, add the AUTHORS and changelog entries, and adapt to the maintainers' feedback.

Parity with the parametric-insurance-design library, which the module comes from, is tested in this repository only (`packages/climada/tests/test_petals_parametric_parity.py`): for the same index, losses, budget and objective, the optimal objective values agree within `1e-6` relative.
