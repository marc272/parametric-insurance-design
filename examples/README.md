# Examples

Three short scripts that run the library on the thesis fixture, an EventSet committed to this repository (`parity/tests/data/thesis_eventset`: 9 Miami assets, the IRIS hurricane catalogue, 10,000 simulated years, losses in USD). Run them from the root of a clone, after `uv sync`:

```bash
uv run python examples/quickstart.py
uv run python examples/tail_risk_objective.py
uv run python examples/portfolio_calibration.py
```

Each script prints its setup and its numbers, and takes a few seconds. The two story scripts also write their figures (PNG, each with a CSV of the plotted data) and their result store to a new temporary directory, whose path they print last.

The three share one setup:

| Item | Setting |
|---|---|
| Portfolio | Asset A1 of the fixture (quickstart, tail-risk objective), or all 9 assets with one owner (portfolio calibration) |
| Basis-risk model | None added: no noise layer and no vulnerability draws. The loss at each asset is a function of the index there |
| Payout | Step payout on the asset's peak wind, 15 bins on [20, 70] m/s, paying nothing below 20 m/s (`below_attachment="zero"`) |
| Basis | `annual`: an outcome is a simulated year, and U is the year's uncovered loss |
| Pricing | Pure premium (the expected payout), at most 1.0 × the expected loss of the training years |
| Split | Year-block holdout: calibrate on years 0–6,999, evaluate on years 7,000–9,999 (out of sample). Values on the training years are printed as in-sample |
| Designs | MSE; E[U]; weighted CVaR, 0.9 CVaR₀.₉₉(U) + 0.1 E[U] |

## `quickstart.py`

The library in one call. `pid.design` calibrates the weighted-CVaR payout of asset A1 on the training years, and `pid.evaluate.kpis` evaluates it on the test years. It uses only `import parametric_insurance_design as pid` and reads the fixture by a relative path, so run it from the repository root.

## `tail_risk_objective.py`

The first idea, the [tail-risk objective](../docs/concepts/tail-risk-objective.md). Asset A1 gets three designs at the same budget: by MSE, by E[U] and by the weighted CVaR. The script prints the expected loss, E[U], VaR₀.₉₉(U) and CVaR₀.₉₉(U) of each design on the test years and, labelled in-sample, on the training years. It draws the three payout functions over the event data, and the exceedance curves of U on the test years.

The script goes through the experiment layer (a config, run into a result store) because the figures of `parametric_insurance_design_viz` read the result store.

## `portfolio_calibration.py`

The second idea, [portfolio calibration](../docs/concepts/portfolio-calibration.md). The 9 assets are designed under three scopes at the same total budget, with each of the three objectives:

- `individual`: one design problem and one budget per asset;
- `portfolio`: one design problem. Each asset keeps its own payout of its own index, and the objective and the budget are on the summed loss and payout, so a payout at one asset can cover a loss at another;
- `cluster`: the same, with one payout per cluster of assets, on the cluster's value-weighted mean index (3 clusters, the thesis's Ward clustering on the training years).

The script prints portfolio-level KPIs, on the test years and, labelled in-sample, on the training years, and draws the payout function of every asset (every cluster, in the cluster scope) per scope. A joint design is determined only at the portfolio level, so the script shows no per-asset uncovered-loss KPI for it, and its per-asset payouts are one optimal design of possibly several. The numbers illustrate the method on the fixture. They are not evidence for or against joint calibration.

## Tests and licence

CI runs `test_examples.py` (`uv run pytest examples`) on every pull request. It runs each script in a fresh process and checks that the output states the setup, labels the training-year values as in-sample, and ranks nothing. `ruff.toml` bans imports of the adapter packages here.

The examples are BSD-3-Clause, under the repository's [LICENSE](../LICENSE).
