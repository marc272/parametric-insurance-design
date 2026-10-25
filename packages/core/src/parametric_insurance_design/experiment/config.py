"""Experiment configuration schema (SPEC §4.2, thesis issues C2, C4, C8).

Owner: MAR-63. Pydantic models for the EventSet path, noise, portfolio
subset, scopes, objectives, payout, pricing, basis, splits, sweeps and output
location; unknown keys are errors
(:class:`~parametric_insurance_design.errors.ConfigError`). Also the thesis
config migration and the canonical config hash used as the cache key
(``records.RUNS.config_hash``).
"""
