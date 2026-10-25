"""Experiment runner: config, executor, result store and sweeps (SPEC §4.2).

ADR 0002 splits SPEC §4.2's ``experiment.py`` into this subpackage, so that
its parts can be built by separate issues without editing the same file:

========================  ======  ==============================================
Module                    Owner   Responsibility
========================  ======  ==============================================
``experiment.config``     MAR-63  Pydantic config schema, thesis config
                                  migration, canonical config hash
``experiment.runner``     MAR-64  Executor: config -> EventSet -> build, solve,
                                  evaluate -> records; content-hashed cache
``experiment.store``      MAR-64  Parquet result store for the
                                  ``records`` schemas, with provenance
``experiment.sweeps``     MAR-65  One-factor-at-a-time sweeps, including
                                  EventSet-rebuilding sweeps
========================  ======  ==============================================

This file stays docstring-only (owner MAR-61); import from the submodules.
"""
