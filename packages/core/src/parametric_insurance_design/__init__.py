"""Design parametric insurance payout functions.

The core library of the parametric-insurance-design project. It holds no
hazard-model dependency; adapters for hazard sources live in separate
distributions. By convention it is imported as ``pid``::

    import parametric_insurance_design as pid
"""

from importlib.metadata import version

__all__ = ["__version__"]

__version__: str = version("parametric-insurance-design")
