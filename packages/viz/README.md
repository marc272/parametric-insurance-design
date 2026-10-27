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
| `command` | The figure set of the `figures` command |
| `errors` | Typed errors, all `ParametricInsuranceDesignError` |

- Depends on the core package only, and never imports an adapter (ADR 0001), the solver or the problem builder (checked in `tests/test_imports.py`).
- Licence: BSD-3-Clause.
