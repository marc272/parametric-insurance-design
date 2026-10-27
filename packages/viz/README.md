# parametric-insurance-design-viz

Figures for [parametric-insurance-design](https://github.com/marc272/parametric-insurance-design). Plots read the core's result store; they never re-run an optimisation (SPEC §3.1 C6).

From the command line, after the runs are in the store:

```console
parametric-insurance-design run CONFIG      # or `sweep CONFIG` if the config has sweeps
parametric-insurance-design figures CONFIG [--out DIR]
```

If the config has `sweeps`, `figures` also needs every sweep point in the store (run `parametric-insurance-design sweep CONFIG` first); a missing point is an error that names it.

`figures` is a core command that imports this package only when it runs. Each figure is written as `<name>.png` with its figure data next to it: `<name>.csv` and, for some figures, `<name>.<part>.csv`.

From Python:

```python
from parametric_insurance_design_viz.reader import ResultReader
from parametric_insurance_design_viz.payout_functions import payout_grid
from parametric_insurance_design_viz.figure_data import write_figure

reader = ResultReader("results/thesis")
runs = reader.runs([run_id_mse, run_id_uncovered, run_id_cvar])  # one scope
write_figure(payout_grid(runs), "figures/")
```

| Module | What it holds |
|---|---|
| `style` | Fonts, palette and labels of the thesis `global_settings` |
| `reader` | Result-store reader: runs, entities, event data under each entity |
| `figure_data` | `FigureOutput` and `write_figure`: the image plus its figure-data CSVs |
| `payout_functions` | Payout-function grid and normalised payout figure |
| `sweep_figures` | Sweep figures (thesis 5.7 to 5.14, A.3): premium reallocation, payout functions along a sweep, tail-basis-risk sensitivity, tail-vs-total trade-off, cluster net advantage and break-even cost |
| `command` | The figure set of the `figures` command |
| `errors` | Typed errors, all `ParametricInsuranceDesignError` |

### Sweep figures

`figures` draws these from the config's sweeps (MAR-112; names as written, `<param>` the swept parameter):

| Figure | Thesis | Shows |
|---|---|---|
| `premium_reallocation` | 5.7 | Premium share per location, individual vs. portfolio scope (weighted-CVaR objective), over the insured values |
| `payout_sweep_<scope>_<entity>_<param>` | 5.8 | The first entity's payout function at every value of `alpha`, `beta`, `budget_loading`, `n_bins`, `noise_level` (weighted CVaR), over the event data and the residual-loss baseline |
| `sensitivity_<param>` | 5.9, 5.10, 5.12 | Portfolio tail basis risk (`cvar_uncovered`) against every swept parameter, per scope x objective; `n_assets` averages its location subsets |
| `tradeoff_<scope>_<param>` | 5.11, A.3 | Tail against total basis risk along `alpha`, `beta`, `n_bins`, `budget_loading` (portfolio scope, weighted CVaR) |
| `net_advantage_<scope>`, `breakeven_cost_<scope>` | 5.13, 5.14 | Transaction-cost saving minus the tail-risk penalty of `C` clusters against the portfolio scope (`n_clusters` sweep), and the break-even cost per contract |

Sweep points whose run failed are not drawn, but each figure's CSV lists them with `ok = False`, and the command reports the figure as `FAILED` (exit 1). On the thesis config that happens for `sensitivity_n_assets`: subsets smaller than the three clusters cannot be clustered.

- Depends on the core package only, and never imports an adapter (ADR 0001), the solver or the problem builder (checked in `tests/test_imports.py`).
- Licence: BSD-3-Clause.
