"""CLIMADA adapter for parametric-insurance-design.

Turns tracks into CLIMADA hazards and impacts, and writes them as the core's
EventSet. Licensed GPL-3.0-or-later because it will import GPLv3 CLIMADA
(ADR 0001). It must never import ``parametric_insurance_design_crc``.
"""

from importlib.metadata import version

__all__ = ["__version__"]

__version__: str = version("parametric-insurance-design-climada")
