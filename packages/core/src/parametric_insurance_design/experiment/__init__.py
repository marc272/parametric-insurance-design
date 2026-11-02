"""Experiment runner: config, executor, result store and sweeps.

The experiment layer, one module per part:

========================  ==============================================
Module                    Responsibility
========================  ==============================================
``experiment.config``     Pydantic config schema, thesis config
                          migration, canonical config hash
``experiment.runner``     Executor: config -> EventSet -> build, solve,
                          evaluate -> records; content-hashed cache
``experiment.store``      Parquet result store for the
                          ``records`` schemas, with provenance
``experiment.sweeps``     One-factor-at-a-time sweeps, including
                          EventSet-rebuilding sweeps
``experiment.kfold``      Pooled out-of-sample KPIs of a k-fold
                          experiment
========================  ==============================================

This file stays docstring-only; import from the submodules.
"""
