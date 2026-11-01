# parametric-insurance-design-viz

Figures for [parametric-insurance-design](https://github.com/marc272/parametric-insurance-design). The figures read the core's result store and the runs' input EventSets. They never solve or re-optimise a design.

From the command line, after the runs are in the store:

```console
parametric-insurance-design run CONFIG      # or `sweep CONFIG` if the config has sweeps
parametric-insurance-design figures CONFIG [--out DIR]
```

`figures` is a core command that imports this package only when it runs. Each figure is written as `<name>.png`, with its figure data next to it as CSV. A run missing from the store is an error that names it (exit status 3). The figures of a failed run are skipped and reported (exit status 1). `parametric-insurance-design figures --help` lists the options.

From Python:

```python
from parametric_insurance_design_viz.reader import ResultReader
from parametric_insurance_design_viz.payout_functions import payout_grid
from parametric_insurance_design_viz.figure_data import write_figure

reader = ResultReader("results/thesis")
runs = reader.runs([run_id_mse, run_id_uncovered, run_id_cvar])  # one scope
write_figure(payout_grid(runs), "figures/")
```

The repository's [examples](https://github.com/marc272/parametric-insurance-design/blob/main/examples/README.md) draw their figures this way.

| Figures | Module | What they show |
|---|---|---|
| `payout_grid_<scope>`, `normalised_payout_<scope>_<entity>` | `payout_functions` | The payout functions of a scope's designs over the event data |
| `kpi_heatmap_<kpi>`, `performance_overview` | `kpi_figures` | Portfolio KPIs per scope × objective, with bootstrap intervals where the config has them. For a k-fold config, the KPIs pooled over the folds |
| `exceedance_<scope>` | `kpi_figures` | The portfolio uncovered loss per return period, one curve per objective |
| `premium_reallocation`, `payout_sweep_…`, `sensitivity_<param>`, `tradeoff_…`, `net_advantage_<scope>`, `breakeven_cost_<scope>` | `sweep_figures` | The config's one-factor-at-a-time sweeps |

Each module's docstring has the details. How the KPI figures treat holdout and k-fold runs and the bootstrap is in the methodology pages on [out-of-sample evaluation](https://github.com/marc272/parametric-insurance-design/blob/main/docs/methodology/out-of-sample.md#figures) and [confidence intervals](https://github.com/marc272/parametric-insurance-design/blob/main/docs/methodology/bootstrap.md#figures).

- Version 0.1.0.dev0, not released: install from a clone of the repository with `uv sync`. Python 3.11 to 3.13.
- Depends on the core package only. It never imports an adapter, the solver or the problem builder (checked in `tests/test_imports.py`).
- Licence: BSD-3-Clause (`LICENSE` in this folder).
- The repository's [README](https://github.com/marc272/parametric-insurance-design#readme) has the status and a quickstart.
