"""Tests of the shared style (MAR-110): the thesis ``global_settings`` palette."""

from __future__ import annotations

import logging

import matplotlib as mpl
import matplotlib.pyplot as plt
import pytest
from matplotlib import font_manager

from parametric_insurance_design_viz import style


def test_palette_is_the_thesis_colour_palette() -> None:
    # configs/global_settings.yaml, COLOR_PALETTE.Methods and .Approaches
    assert style.OBJECTIVE_COLORS == {
        "mse": "#cc0707",
        "expected_uncovered": "#7ebfee",
        "weighted_cvar": "#0b356d",
    }
    assert {k: (v.linestyle, v.marker) for k, v in style.SCOPE_STYLES.items()} == {
        "individual": (":", "^"),
        "cluster": ("--", "s"),
        "portfolio": ("-", "o"),
    }


def test_font_is_the_thesis_font() -> None:
    assert style.FONT == style.Font(
        family="Times New Roman",
        label_size=12,
        entry_size=11,
        legend_size=12,
        tick_size=11,
        title_size=12,
        subtitle_size=11,
    )
    assert style.SERIF_FALLBACK[0] == "Times New Roman"


def test_labels_and_fallbacks() -> None:
    assert style.objective_label("mse") == "Residual loss objective"
    assert style.objective_label("weighted_cvar") == "Weighted tail risk objective"
    assert style.objective_label("new_thing") == "New thing objective"
    assert style.objective_color("new_thing") == style.DEFAULT_COLOR
    assert style.scope_label("cluster") == "Cluster scope"
    assert style.scope_label("by_region") == "By region scope"


def test_font_family_is_installed() -> None:
    family = style.font_family()
    assert family in style.SERIF_FALLBACK
    assert family in {f.name for f in font_manager.fontManager.ttflist}


def test_style_context_applies_and_restores(caplog: pytest.LogCaptureFixture) -> None:
    before = mpl.rcParams["font.family"]
    with caplog.at_level(logging.WARNING, logger="matplotlib"), style.style():
        assert mpl.rcParams["font.family"] == [style.font_family()]
        assert mpl.rcParams["mathtext.fontset"] == "stix"
        assert mpl.rcParams["legend.fontsize"] == style.FONT.legend_size
        fig, ax = plt.subplots()
        ax.set_title(r"Attachment $x_-$")
    fig.canvas.draw()  # fonts are looked up at draw time, after the block
    plt.close(fig)
    assert not [r for r in caplog.records if "findfont" in r.getMessage()]
    assert mpl.rcParams["font.family"] == before
