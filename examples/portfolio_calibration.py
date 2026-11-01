"""Portfolio calibration: nine assets under three scopes at the same total budget.

Prints the setup and the portfolio KPIs; writes the payout functions to a new
temporary directory. Run ``uv run python examples/portfolio_calibration.py``.
"""

import tempfile
from pathlib import Path

import matplotlib

from parametric_insurance_design.experiment import runner
from parametric_insurance_design.experiment.config import parse_config
from parametric_insurance_design_viz.figure_data import write_figure
from parametric_insurance_design_viz.payout_functions import AxisLabels, payout_grid
from parametric_insurance_design_viz.reader import ResultReader, entity_events

matplotlib.use("Agg")  # write image files, open no window
FIXTURE = Path(__file__).resolve().parents[1] / "parity/tests/data/thesis_eventset"
NAMES = {"mse": "MSE", "expected_uncovered": "E[U]", "weighted_cvar": "WCVaR"}
SPLITS = {"test": "test (out of sample)", "train": "train (in sample)"}
KPIS = ("expected_loss", "expected_uncovered", "cvar_uncovered")
out = Path(tempfile.mkdtemp(prefix="pid-portfolio-"))
payout = {"attachment": 20.0, "limit": 70.0, "n_bins": 15, "below_attachment": "zero"}
ward = {"kind": "thesis_ward", "beta_tail": 0.9}
cluster = {"kind": "cluster", "n_clusters": 3, "strategy": ward}
wcvar = {"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.99}
config = parse_config(
    {
        "schema_version": 1,
        "name": "example-portfolio-calibration",
        "eventset": {"path": str(FIXTURE)},
        "threshold": {"value": 20.0},  # drops rows that lose nothing and pay nothing
        "basis": "annual",
        "sample": {"kind": "holdout", "train_fraction": 0.7},
        "payout": payout,
        "scopes": [{"kind": "individual"}, {"kind": "portfolio"}, cluster],
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
entities = next(r for r in runs if r.scope == "cluster").entities
members = entities.groupby("entity_id").location_id.agg(" ".join).items()
print(f"""Portfolio calibration: one owner's 9 assets, 3 scopes, 1 total budget. Setup:
  portfolio         the 9 Miami assets of the thesis fixture (IRIS, {years:,} years)
  basis-risk model  none added (no noise layer, no vulnerability draws): the loss
                    at each asset is a function of the index there
  payout            15-bin step payout on [20, 70] m/s of peak wind; 0 below 20 m/s
  basis             annual: U is the portfolio's uncovered loss in a year [USD]
  pricing           pure premium (expected payout) <= 1.0 x expected loss on the
                    train years, per asset or in total: the same total budget
  split             year-block holdout: train years 0-{train - 1:,}, test years \
{train:,}-{years - 1:,}
  designs           MSE; E[U]; WCVaR = 0.9 CVaR_0.99(U) + 0.1 E[U]
  individual scope  9 design problems: each asset on its own loss and budget
  portfolio scope   1 design problem: a payout per asset on its own index; the
                    objective and the budget are on the summed loss and payout
  cluster scope     as portfolio, with a payout per cluster on the value-weighted
                    mean index of its assets; 3 thesis Ward clusters (train years):
                    {", ".join(f"{c} = {m}" for c, m in members)}
Portfolio KPIs [USD]; CVaR of U at 0.99, the 100-year level
scope       design  years                      E[loss]         E[U] CVaR_0.99(U)""")
for run in runs:
    run.require_complete()
    k = run.kpis[run.kpis.level == "portfolio"].set_index(["eval_split", "kpi"]).value
    for split, label in SPLITS.items():
        values = "".join(f"{k[split, kpi]:>13,.0f}" for kpi in KPIS)
        print(f"{run.scope:<12}{NAMES[run.objective]:<8}{label:<21}{values}")
print("""An illustration on the 9-asset thesis fixture; not evidence for or against
joint calibration. Joint designs are determined only at the portfolio level: their
payout per asset is one optimal design of possibly several.""")
prepared = runner.prepare_eventset(config, data.eventset)
labels = AxisLabels(index_unit="m/s", payout_unit="USD")
for scope in config.scopes:
    group = [r for r in runs if r.scope == scope.kind]
    events = entity_events(prepared, scope.build(), group[0].problem_specs())
    write_figure(payout_grid(group, events=events, labels=labels), out)
print(f"Payout functions per asset (per cluster), one figure per scope, in {out}")
