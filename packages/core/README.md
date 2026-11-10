# parametric-insurance-design

The core library of [parametric-insurance-design](https://github.com/marc272/parametric-insurance-design). It designs parametric insurance payouts: a step payout on a hazard index, calibrated on simulated events by an optimisation under a premium budget. It carries the project's two ideas, which work separately or together:

- **the tail-risk objective:** the weighted CVaR of the uncovered loss, α·CVaR<sub>β</sub>(U) + (1 − α)·E[U], solved as a linear program, next to the MSE and E[U] objectives;
- **portfolio (joint) calibration:** the payouts of one owner's sites calibrated jointly, on the total loss (the portfolio and cluster scopes), or each site on its own (the individual scope).

```python
import parametric_insurance_design as pid
```

The top level holds the vocabulary of both ideas (`WeightedCVaR`, `ExpectedUncovered`, `MSE`; `Individual`, `Portfolio`, `Cluster`; `StepPayout`, `PurePremium`, `CostOfCapitalLoad`, `Budget`) and one call, `pid.design`, which builds and solves every design problem of a scope. Evaluation is in `pid.evaluate`, `pid.splits` and `pid.bootstrap`. The `parametric-insurance-design` command runs a config's designs and sweeps into a result store (`run`, `sweep`) and draws its figures (`figures`, with the viz package).

The repository's [README](https://github.com/marc272/parametric-insurance-design#readme) has the status and a quickstart, and its [documentation index](https://github.com/marc272/parametric-insurance-design/blob/main/docs/README.md) explains the method.

- Version 0.1.0.dev0, not released: install from a clone of the repository with `uv sync`.
- Python 3.11 to 3.13, numpy ≥ 1.26, pandas ≥ 2.1.
- No hazard-model dependency. Hazard data comes in as EventSet files, for example from the CLIMADA adapter package.
- Licence: BSD-3-Clause (`LICENSE` in this folder).
