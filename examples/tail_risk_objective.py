"""The tail-risk objective: MSE, E[U] and weighted-CVaR payouts for one asset.

Prints the setup and the KPIs; writes the payout functions and the exceedance
curves of the uncovered loss to a new temporary directory. From a clone, run
``uv run python examples/tail_risk_objective.py``.
"""

import tempfile
from pathlib import Path

import matplotlib

from parametric_insurance_design.experiment import runner
from parametric_insurance_design.experiment.config import parse_config
from parametric_insurance_design_viz.figure_data import write_figure
from parametric_insurance_design_viz.kpi_figures import exceedance_curves
from parametric_insurance_design_viz.payout_functions import AxisLabels, payout_grid
from parametric_insurance_design_viz.reader import ResultReader, entity_events

matplotlib.use("Agg")  # write image files, open no window
FIXTURE = Path(__file__).resolve().parents[1] / "parity/tests/data/thesis_eventset"
NAMES = {"mse": "MSE", "expected_uncovered": "E[U]", "weighted_cvar": "WCVaR"}
SPLITS = {"test": "test (out of sample)", "train": "train (in sample)"}
KPIS = ("expected_loss", "expected_uncovered", "var_uncovered", "cvar_uncovered")
out = Path(tempfile.mkdtemp(prefix="pid-tail-risk-"))
payout = {"attachment": 20.0, "limit": 70.0, "n_bins": 15, "below_attachment": "zero"}
wcvar = {"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.99}
config = parse_config(
    {
        "schema_version": 1,
        "name": "example-tail-risk-objective",
        "eventset": {"path": str(FIXTURE)},
        "portfolio": {"location_ids": ["A1"]},
        "threshold": {"value": 20.0},  # drops rows that lose nothing and pay nothing
        "basis": "annual",
        "sample": {"kind": "holdout", "train_fraction": 0.7},
        "payout": payout,
        "scopes": [{"kind": "individual"}],
        "objectives": [{"kind": "mse"}, {"kind": "expected_uncovered"}, wcvar],
        "pricing": {"kind": "pure"},
        "constraints": [{"kind": "budget", "loading": 1.0}],
        "evaluation": {"beta": 0.99},
        "output": {"directory": str(out / "store")},
    }
)
data = runner.load_input(config)
outcomes = runner.run_config(config, data=data)
runs = ResultReader(out / "store").runs(o.run_id for o in outcomes)
years = data.eventset.metadata.n_years
train = int(0.7 * years)
print(f"""Tail-risk objective: three payout designs for one asset at one budget. Setup:
  portfolio         asset A1 of the thesis fixture (9 Miami assets, IRIS,
                    {years:,} simulated years)
  basis-risk model  none added (no noise layer, no vulnerability draws): the loss
                    at A1 is a function of the index there
  payout            15-bin step payout on [20, 70] m/s of peak wind; 0 below 20 m/s
  basis             annual: U is the uncovered loss of a simulated year [USD]
  pricing           pure premium (the expected payout) <= 1.0 x the expected loss,
                    both on the train years
  split             year-block holdout: train years 0-{train - 1:,}, test years \
{train:,}-{years - 1:,}
  designs           MSE; E[U]; WCVaR = 0.9 CVaR_0.99(U) + 0.1 E[U]
KPIs of A1 [USD]; VaR and CVaR of U at 0.99, the 100-year level
design  years                      E[loss]         E[U]  VaR_0.99(U) CVaR_0.99(U)""")
for run in runs:
    run.require_complete()
    k = run.kpis[run.kpis.level == "portfolio"].set_index(["eval_split", "kpi"]).value
    for split, label in SPLITS.items():
        values = "".join(f"{k[split, kpi]:>13,.0f}" for kpi in KPIS)
        print(f"{NAMES[run.objective]:<8}{label:<21}{values}")
print("""Each design minimises its own objective on the train years only. One asset,
one split, no added basis risk: an illustration of the method, not evidence for
or against any objective.""")
prepared = runner.prepare_eventset(config, data.eventset)
events = entity_events(prepared, config.scopes[0].build(), runs[0].problem_specs())
labels = AxisLabels(index_unit="m/s", payout_unit="USD")
write_figure(payout_grid(runs, events=events, labels=labels), out)
write_figure(exceedance_curves(runs, eval_split="test", labels=labels), out)
print(f"Payout functions and test-year exceedance curves of U written to {out}")
