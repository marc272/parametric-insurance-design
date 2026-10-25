"""Climate Risk Commons (CRC) and VELO/CDT adapter for parametric-insurance-design.

Turns CRC/VELO assets and hazards into the core's EventSet. Licensed
AGPL-3.0-or-later because it will import the AGPL-licensed CRC SDK
(ADR 0001).
"""

from importlib.metadata import version

__all__ = ["__version__"]

__version__: str = version("parametric-insurance-design-crc")
