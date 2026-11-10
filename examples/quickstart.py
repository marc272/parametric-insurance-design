"""Quickstart: a tail-risk payout design for one asset, in one call.

Run from the root of a clone: ``uv run python examples/quickstart.py``.
"""

import parametric_insurance_design as pid

# Asset A1 of the thesis fixture: 9 Miami assets, IRIS, 10,000 simulated years.
es = pid.EventSet.from_parquet("parity/tests/data/thesis_eventset")
es = es.select_locations(["A1"])
train, test = pid.splits.holdout(es, train_fraction=0.7)  # first 70 % of the years
scope, basis = pid.Individual(), pid.Basis.ANNUAL  # annual: an outcome is a year
(result,) = pid.design(
    es,
    scope,
    pid.StepPayout(attachment=20.0, limit=70.0, n_bins=15, below_attachment="zero"),
    pid.WeightedCVaR(alpha=0.9, beta=0.99),  # 0.9 CVaR_0.99(U) + 0.1 E[U]
    basis=basis,
    constraints=(pid.Budget(1.0),),  # pure premium <= 1.0 x expected loss
    sample=train,  # calibrate on the train years only
)
kpis = pid.evaluate.kpis(
    es, scope, [result], basis=basis, beta=0.99, run_id="quickstart", sample=test
)
value = kpis[kpis.level == "portfolio"].set_index("kpi").value
print(
    "Setup: asset A1 of the thesis fixture; no added basis risk (no noise layer, no\n"
    "vulnerability draws); 15-bin step payout on [20, 70] m/s of peak wind, 0 below\n"
    "20 m/s; weighted CVaR design (alpha 0.9, beta 0.99); pure premium <= 1.0 x\n"
    f"expected loss; annual basis; calibrated on years 0-{train.years[-1]:,}.\n"
    f"Test years {test.years[0]:,}-{test.years[-1]:,} (out of sample), USD: "
    f"E[U] = {value['expected_uncovered']:,.0f}, "
    f"CVaR_0.99(U) = {value['cvar_uncovered']:,.0f}, "
    f"E[loss] = {value['expected_loss']:,.0f}"
)
