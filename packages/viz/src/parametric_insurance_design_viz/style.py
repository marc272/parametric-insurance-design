"""Shared figure style: fonts, palette and labels (thesis ``global_settings``).

Owner: MAR-110. Every figure of this package draws inside :func:`style` and
takes its colours, line styles and labels from here, so the figure set reads
as one system. The values port ``COLOR_PALETTE`` of the thesis
``configs/global_settings.yaml`` (parametric-insurance-framework), keyed by
the component names of the result store (``runs.objective``, ``runs.scope``)
instead of the thesis method and approach names:

=========================================  ======================
Thesis key                                 Result-store name
=========================================  ======================
``pure_basis_risk_minimization``           ``mse``
``pure_uncovered_loss_minimization``       ``expected_uncovered``
``weighted_cvar_minimization``             ``weighted_cvar``
``individual_optimization``                ``individual``
``cluster_optimization``                   ``cluster``
``integrated_portfolio_optimization``      ``portfolio``
=========================================  ======================

The thesis font is Times New Roman. Where it is not installed (e.g. on Linux
CI), :func:`font_family` falls back along :data:`SERIF_FALLBACK` to STIX,
which ships with matplotlib and matches Times. The family is resolved to an
installed font when the style is applied, because matplotlib looks fonts up
when a figure is saved, which may be after the style block has ended; so
there are no font warnings and saved figures use the font they were drawn
with.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Final, cast

import matplotlib as mpl
from matplotlib import font_manager

__all__ = [
    "BENCHMARK_OBJECTIVE",
    "DEFAULT_COLOR",
    "EVENT_COLOR",
    "FONT",
    "OBJECTIVE_COLORS",
    "OBJECTIVE_LABELS",
    "SCOPE_LABELS",
    "SCOPE_STYLES",
    "SERIF_FALLBACK",
    "Font",
    "ScopeStyle",
    "font_family",
    "objective_color",
    "objective_label",
    "rc_params",
    "scope_label",
    "style",
]


@dataclass(frozen=True)
class Font:
    """Font family and sizes in points (thesis ``COLOR_PALETTE.Font``).

    Parameters
    ----------
    family : str
        Preferred font family.
    label_size, entry_size, legend_size, tick_size, title_size, subtitle_size
        Sizes of axis labels, table entries, legends, tick labels, figure
        titles and subtitles.
    """

    family: str
    label_size: float
    entry_size: float
    legend_size: float
    tick_size: float
    title_size: float
    subtitle_size: float


@dataclass(frozen=True)
class ScopeStyle:
    """Line style and marker of a scope (thesis ``COLOR_PALETTE.Approaches``).

    Parameters
    ----------
    linestyle : str
        Matplotlib line style.
    marker : str
        Matplotlib marker.
    """

    linestyle: str
    marker: str


FONT: Final[Font] = Font(
    family="Times New Roman",
    label_size=12,
    entry_size=11,
    legend_size=12,
    tick_size=11,
    title_size=12,
    subtitle_size=11,
)
"""The thesis font settings."""

SERIF_FALLBACK: Final[tuple[str, ...]] = (
    FONT.family,
    "Times",
    "STIXGeneral",
    "DejaVu Serif",
)
"""Serif families tried in order; STIXGeneral ships with matplotlib."""

OBJECTIVE_COLORS: Final[dict[str, str]] = {
    "mse": "#cc0707",
    "expected_uncovered": "#7ebfee",
    "weighted_cvar": "#0b356d",
}
"""Colour per objective (thesis ``COLOR_PALETTE.Methods``)."""

OBJECTIVE_LABELS: Final[dict[str, str]] = {
    "mse": "Residual loss objective",
    "expected_uncovered": "Uncovered loss objective",
    "weighted_cvar": "Weighted tail risk objective",
}
"""Legend label per objective (thesis ``prettify_objective_label``)."""

SCOPE_STYLES: Final[dict[str, ScopeStyle]] = {
    "individual": ScopeStyle(linestyle=":", marker="^"),
    "cluster": ScopeStyle(linestyle="--", marker="s"),
    "portfolio": ScopeStyle(linestyle="-", marker="o"),
}
"""Line style and marker per scope (thesis ``COLOR_PALETTE.Approaches``)."""

SCOPE_LABELS: Final[dict[str, str]] = {
    "individual": "Individual scope",
    "cluster": "Cluster scope",
    "portfolio": "Portfolio scope",
}
"""Label per scope (thesis ``prettify_scope_label``)."""

BENCHMARK_OBJECTIVE: Final[str] = "mse"
"""The benchmark of normalised figures: the residual loss (MSE) objective."""

EVENT_COLOR: Final[str] = "grey"
"""Colour of event-data overlays (scatter, density)."""

DEFAULT_COLOR: Final[str] = "black"
"""Colour of an objective without an entry in :data:`OBJECTIVE_COLORS`."""


def objective_color(objective: str) -> str:
    """Return the colour of an objective.

    Parameters
    ----------
    objective : str
        Objective name, as in ``runs.objective``.

    Returns
    -------
    str
        Its thesis colour, or :data:`DEFAULT_COLOR` for an objective the
        thesis did not have (as the thesis did).
    """
    return OBJECTIVE_COLORS.get(objective, DEFAULT_COLOR)


def objective_label(objective: str) -> str:
    """Return the legend label of an objective.

    Parameters
    ----------
    objective : str
        Objective name, as in ``runs.objective``.

    Returns
    -------
    str
        Its thesis label, or ``"<Name> objective"`` for another objective.
    """
    if objective in OBJECTIVE_LABELS:
        return OBJECTIVE_LABELS[objective]
    return f"{objective.replace('_', ' ').capitalize()} objective"


def scope_label(scope: str) -> str:
    """Return the label of a scope.

    Parameters
    ----------
    scope : str
        Scope name, as in ``runs.scope``.

    Returns
    -------
    str
        Its thesis label, or ``"<Name> scope"`` for another scope.
    """
    if scope in SCOPE_LABELS:
        return SCOPE_LABELS[scope]
    return f"{scope.replace('_', ' ').capitalize()} scope"


def font_family() -> str:
    """Return the first installed family of :data:`SERIF_FALLBACK`.

    Returns
    -------
    str
        Times New Roman where installed, else the next available fallback.
        STIXGeneral ships with matplotlib, so one is always found.
    """
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for family in SERIF_FALLBACK:
        if family in installed:
            return family
    return SERIF_FALLBACK[-1]  # pragma: no cover - DejaVu ships with matplotlib


def rc_params() -> dict[str, Any]:
    """Return the matplotlib settings of the thesis style.

    Returns
    -------
    dict
        rcParams: the serif font of :func:`font_family`, STIX maths, the
        thesis sizes.
    """
    return {
        "font.family": [font_family()],
        "mathtext.fontset": "stix",
        "axes.labelsize": FONT.label_size,
        "axes.titlesize": FONT.label_size,
        "xtick.labelsize": FONT.tick_size,
        "ytick.labelsize": FONT.tick_size,
        "legend.fontsize": FONT.legend_size,
        "figure.titlesize": FONT.title_size,
    }


@contextmanager
def style() -> Iterator[None]:
    """Draw inside the thesis style.

    Yields
    ------
    None
        Inside the block, :func:`rc_params` is in effect; the previous
        settings are restored afterwards.
    """
    with mpl.rc_context(cast(Any, rc_params())):
        yield
