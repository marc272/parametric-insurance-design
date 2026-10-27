# parametric-insurance-design-viz

Figures for [parametric-insurance-design](https://github.com/marc272/parametric-insurance-design). Plots read the core's result store; they never re-run an optimisation (SPEC §3.1 C6).

From the command line, after the runs are in the store:

```console
parametric-insurance-design run CONFIG
parametric-insurance-design figures CONFIG [--out DIR]
```

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
| `kpi_figures` | KPI heatmaps, performance overview and exceedance curves |
| `command` | The figure set of the `figures` command |
| `errors` | Typed errors, all `ParametricInsuranceDesignError` |

- Depends on the core package only, and never imports an adapter (ADR 0001), the solver or the problem builder (checked in `tests/test_imports.py`).
- Licence: BSD-3-Clause.

### KPI figures (`kpi_figures`)

`figures` also draws, from the `kpis` and `exceedance` tables of the store:

| Figure | Thesis | What it shows |
|---|---|---|
| `kpi_heatmap_cvar_uncovered`, `kpi_heatmap_expected_uncovered` | Notebook "Portfolio-level performance comparison" | One portfolio KPI per scope x objective, coloured by its change against the baseline (green lower, red higher) |
| `performance_overview` | Figure 5.5, Table A.2 | Tail and total basis risk, bars grouped by scope, dotted baseline |
| `exceedance_<scope>` | Figure 5.6 (portfolio) | Portfolio uncovered loss per return period, one curve per objective, VaR return period `1/(1-beta)` marked |

- The baseline is the first scope with the `mse` objective (the thesis' individual scope and residual loss objective), or the first scope's first objective without `mse`.
- KPIs are read on the `test` split when every run has one, else `full`; VaR/CVaR at the runs' `evaluation_beta`. Curves are `event` on the event bases and `aep` on the annual basis.
- The curves use the return periods the runner stored. The portfolio `var_uncovered` KPI is the same quantile at `1/(1-beta)`, so it is added as that point (`source = "kpis"` in the CSV) when the store has none there.
- If any run failed, the heatmaps and the overview are skipped and reported (exit 1), as is the exceedance figure of the failed scope.
