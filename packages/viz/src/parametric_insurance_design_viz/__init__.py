"""Figures for parametric-insurance-design.

Plotting reads results from the core's result store and never re-runs an
optimisation. This package must never import an adapter
(``parametric_insurance_design_crc`` or ``parametric_insurance_design_climada``).
"""

from importlib.metadata import version

__all__ = ["__version__"]

__version__: str = version("parametric-insurance-design-viz")
