"""Submodules reachable as ``pid.<module>`` (MAR-61, MAR-153)."""

from __future__ import annotations

import importlib
import pkgutil

import parametric_insurance_design as pid


def test_bootstrap_and_riskmeasures_are_package_attributes() -> None:
    # MAR-153: MAR-143 added these modules; they are imported by __init__.
    from parametric_insurance_design import bootstrap, riskmeasures

    assert pid.bootstrap is bootstrap
    assert pid.riskmeasures is riskmeasures
    assert callable(pid.bootstrap.premium_replicates)
    assert callable(pid.riskmeasures.var_cvar)
    assert "bootstrap" in pid.__all__
    assert "riskmeasures" in pid.__all__


def test_every_library_module_is_a_package_attribute() -> None:
    # Every top-level module of the core library except the CLI is imported
    # by __init__ (ADR 0002 §1), and listed in __all__.
    names = {
        m.name
        for m in pkgutil.iter_modules(pid.__path__)
        if not m.ispkg and not m.name.startswith("_") and m.name != "cli"
    }
    for name in sorted(names):
        module = importlib.import_module(f"parametric_insurance_design.{name}")
        assert getattr(pid, name, None) is module, name
        assert name in pid.__all__, name
