"""Figures for parametric-insurance-design.

Plotting reads results from the core's result store and never re-runs an
optimisation (SPEC §3.1 C6). This package must never import an adapter
(``parametric_insurance_design_crc`` or ``parametric_insurance_design_climada``),
nor the core's solver or problem builder.

Modules: :mod:`.style` (fonts, palette, labels), :mod:`.reader` (result-store
reader), :mod:`.figure_data` (image plus figure-data CSVs),
:mod:`.payout_functions` (payout figures), :mod:`.command` (the figure set of
``parametric-insurance-design figures``) and :mod:`.errors`.
"""

from importlib.metadata import version

__all__ = ["__version__"]

__version__: str = version("parametric-insurance-design-viz")
