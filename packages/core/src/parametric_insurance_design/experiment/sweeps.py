"""One-factor-at-a-time sweeps (SPEC §4.2).

Owner: MAR-65. Optimisation-parameter sweeps (alpha, beta, budget_loading,
n_bins, n_clusters) and simulation-parameter sweeps that rebuild the EventSet
(noise level, number of assets). Every sweep point is a cached run whose
``records.RUNS.source`` is ``"<param>_sweep"``, as in the thesis.
"""
