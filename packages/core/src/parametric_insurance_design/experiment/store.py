"""Parquet result store (SPEC §4.2, thesis issue C5).

Owner: MAR-64. Persists and reads the tables defined in
:mod:`parametric_insurance_design.records` (one Parquet dataset per table,
written with ``TableSchema.arrow_schema``), with per-run provenance: config
hash, package versions, input checksum, solver, status and timings.
"""
