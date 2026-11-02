# Changelog

All notable changes to the distributions in this repository are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html). A release has one subsection per distribution. Entries are written at release time, not per pull request.

## [0.1.0] - 2026-11-02

The first release of the core library and its figures package. It carries the two ideas of the master's thesis the project is built on: a tail-risk objective for the payout design, and the joint calibration of one owner's sites. The entries below describe the method and the tool. They report no results; where a number appears, it is a setting, not an outcome.

The two adapters, `parametric-insurance-design-climada` and `parametric-insurance-design-crc`, stay at `0.1.0.dev0` and are not part of this release (see [Not released](#not-released)).

### parametric-insurance-design 0.1.0

The core library (BSD-3-Clause, Python 3.11 to 3.13). It has no hazard-model dependency: hazard data comes in as EventSet files.

#### Added

- **EventSet data contract (schema v1).** One table of events with a hazard index and a loss per location, plus years, rates, draw ids and a location table. Parquet I/O with typed validation, a content hash over the data and the metadata, atomic writes, a structured record of the transforms applied, and `select_locations` for subsets of a portfolio.
- **Design problems from combinable blocks.**
  - Payout: `StepPayout`, one non-decreasing payout level per index bin between an attachment and a limit, capped at the largest loss. `below_attachment` chooses whether outcomes below the attachment pay nothing (`"zero"`) or the first bin's level (`"first_bin"`, the thesis behaviour and the default).
  - Objectives on the uncovered loss U: `MSE`, `ExpectedUncovered` (E[U]) and `WeightedCVaR`, α·CVaR<sub>β</sub>(U) + (1 − α)·E[U]. The E[U] and weighted-CVaR problems are linear programs, the MSE problem a quadratic program.
  - Scopes: `Individual` (each site calibrated on its own), `Portfolio` (each site keeps its own payout on its own index, and the objective and the budget apply to the owner's total) and `Cluster` (one payout per cluster of sites, calibrated jointly or, with `joint=False`, one cluster at a time). `ThesisWardClustering` ports the thesis clustering.
  - Pricing: `PurePremium`, and `CostOfCapitalLoad`, a cost-of-capital load that stays inside the linear program and reduces to the pure premium at a zero rate. Constraint: `Budget`, a premium at most a loading times the expected loss.
- **One call, `pid.design`,** builds and solves every design problem of a scope. The low-level path is `pid.problem.build_problems`, then `pid.solve.solve` for each problem.
- **Solver policy with no silent failures.** Each problem class has an ordered list of solvers (Clarabel, HiGHS, then SCS for the linear programs; OSQP at tightened accuracy, then Clarabel, for MSE). Every attempt is recorded, and a problem no solver accepts raises `SolveError` with the attempts attached. A separate policy reproduces the thesis solver settings for the parity runs.
- **Evaluation.**
  - KPIs of the uncovered loss, the payout and the premium, per entity and for the portfolio, on two bases: per event (event-conditional) and per simulated year (annual, on which CVaR has a return-period meaning and the premium is annual). Exceedance curves over configurable return periods.
  - Out-of-sample evaluation on year-block holdout and k-fold splits, with checks against leakage between train and test years; KPIs pooled over the folds.
  - Block-bootstrap confidence intervals over simulated years for every KPI, and paired differences between two designs evaluated on the same resampled years.
- **The thesis noise layer** (`parametric_insurance_design.noise`, imported by its full name), ported bit for bit: the thesis's basis-risk model, which repeats each event and multiplies each location's loss by a mean-one lognormal factor, leaving the index unchanged.
- **Experiment layer and command line.** A YAML config validated by pydantic, one-factor-at-a-time sweeps (α, β, budget loading, number of bins, number of clusters, and the EventSet-rebuilding sweeps over the noise level and the number of assets), parallel execution, a content-hashed run cache and a Parquet result store with a manifest per run. The `parametric-insurance-design` command runs a config's designs (`run`) and sweeps (`sweep`), and, with the viz package installed, draws its figures (`figures`) and exports website bundles (`export-site`).
- **Provenance.** Each run id is a hash of the config hash, the checksum of the EventSet as loaded, the package version and the solver policy, so results computed by different code versions are never mixed. Every run records its config hash, scope, objective, pricing, payout, calibration split and fold, parameters, solver and status, the EventSet checksum and the package version; a failed run is recorded with its error, not dropped.

#### Not included

- Robust design under uncertainty (`parametric_insurance_design.robust`) is not implemented yet and raises `NotImplementedError`.

### parametric-insurance-design-viz 0.1.0

Figures for the core library (BSD-3-Clause, Python 3.11 to 3.13). It reads the core's result store and the runs' input EventSets, and it never solves or re-optimises a design.

#### Added

- **Figures**, each written as a PNG with its figure data as CSV: the payout functions of a scope's designs; KPI heatmaps and a performance overview per scope × objective, with bootstrap intervals where the config has them and pooled k-fold KPIs for a k-fold config; exceedance curves of the portfolio's uncovered loss; and the sweep figures (premium reallocation, payout sweeps, sensitivities, the tail-versus-total trade-off, and the thesis's transaction-cost figures over the number of clusters).
- **A result-store reader** (`ResultReader`) that returns stored runs. The core's `figures` and `export-site` commands import this package only when they run.
- **Website bundles** (`export-site`): JSON and Arrow IPC files with a manifest that states the setup of every number in the bundle (portfolio, basis, basis-risk model, pricing and split), the config hash and the versions, and a size budget that the export checks.

### Repository

Not a distribution, but part of the state this release was made from.

- **Parity with the thesis code.** [`parity/REPORT.md`](parity/REPORT.md) compares the core's runs on the thesis event set (9 Miami assets, the IRIS North Atlantic 10,000-year catalogue, the thesis noise layer, pure pricing, the event-conditional basis) with the thesis code's result tables: the 9 default designs (3 scopes × 3 objectives), the optimisation-parameter sweeps and the two simulation sweeps. It explains every difference it finds.
- **Documentation.** Concept pages on the tail-risk objective, portfolio calibration and their combination, with a glossary; methodology pages on out-of-sample evaluation, the bootstrap, the annual basis, pricing and vulnerability uncertainty; ADRs on the licences, the core interfaces, the website stack and the repository structure.
- **Examples.** A quickstart and a script for each idea under [`examples/`](examples/README.md), run in CI.
- **CI.** ruff, pyright and pytest on Python 3.11 to 3.13, enforced import boundaries between the core, the figures package and the adapters, wheel builds with licence metadata checks, and the parity, example and adapter test jobs.

### Not released

- **`parametric-insurance-design-climada` (0.1.0.dev0, GPL-3.0-or-later).** The CLIMADA adapter, in its own pixi environment: the IRIS catalogue download and merge with checksums, the track → wind field → impact pipeline that writes an EventSet, a cat-in-a-circle index, and vulnerability draws. It regenerates the thesis event-loss table, the parity fixture, bit for bit (the adapter section of the parity report).
- **`parametric-insurance-design-crc` (0.1.0.dev0, AGPL-3.0-or-later).** A placeholder for the Climate Risk Commons adapter.
