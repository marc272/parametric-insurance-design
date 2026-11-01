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


# -- money tick labels (MAR-197) ---------------------------------------------------


def thesis_millions(value: float) -> str:
    """The thesis ``format_millions`` of ``kpi_figures`` before MAR-197."""
    return f"{value * 1e-6:.1f}M"


def thesis_money(value: float) -> str:
    """The compact ``_money`` of ``sweep_figures`` before MAR-197."""
    sign = "-" if value < 0 else ""
    size = abs(value)
    if size >= 1e6:
        return f"{sign}{size * 1e-6:.1f}M"
    if size >= 1e3:
        return f"{sign}{size * 1e-3:.0f}k"
    return f"{sign}{size:.0f}"


def axis_labels(formatter: style.MoneyFormatter, lo: float, hi: float) -> list[str]:
    """Tick labels of a y axis on ``[lo, hi]`` drawn with ``formatter``."""
    fig, ax = plt.subplots()
    ax.set_ylim(lo, hi)
    ax.yaxis.set_major_formatter(formatter)
    fig.canvas.draw()
    labels = [t.get_text() for t in ax.get_yticklabels()]
    plt.close(fig)
    return labels


@pytest.mark.parametrize(
    "ticks",
    [
        [0.0, 1e6, 2e6, 3e6, 4e6, 5e6, 6e6, 7e6],  # the thesis exceedance curves
        [0.0, 5e5, 1e6, 1.5e6, 2e6, 2.5e6],
        [-1e6, 0.0, 1e6, 2e6],
        [0.0, 2e6, 4e6, 6e6, 8e6, 10e6, 12e6],
        [0.0, 2.5e6, 5e6, 7.5e6, 10e6],
    ],
)
def test_money_labels_in_millions_are_the_thesis_labels(ticks: list[float]) -> None:
    assert style.MoneyFormatter("M").format_ticks(ticks) == [
        thesis_millions(v) for v in ticks
    ]


@pytest.mark.parametrize(
    "ticks",
    [
        [-6e5, -4e5, -2e5, 0.0, 2e5, 4e5, 6e5, 8e5],  # thesis net advantage
        [0.0, 2e4, 4e4, 6e4, 8e4, 1e5, 1.2e5],  # thesis break-even cost
        [25e3, 50e3, 75e3, 100e3, 125e3],  # thesis transaction costs
        [0.0, 5e5, 1e6, 1.5e6, 2e6],
        [0.0, 100.0, 200.0, 300.0],
    ],
)
def test_compact_money_labels_are_the_thesis_labels(ticks: list[float]) -> None:
    assert style.MoneyFormatter().format_ticks(ticks) == [
        thesis_money(v) for v in ticks
    ]


@pytest.mark.parametrize(
    ("prefix", "ticks", "expected"),
    [
        (  # example 1 before MAR-197: 0.0M, 0.0M, 0.1M, 0.1M, 0.2M, ...
            "M",
            [0.0, 5e4, 1e5, 1.5e5, 2e5],
            ["0.00M", "0.05M", "0.10M", "0.15M", "0.20M"],
        ),
        ("M", [1e6, 1.25e6, 1.5e6], ["1.00M", "1.25M", "1.50M"]),
        ("M", [0.0, 2e3, 4e3], ["0.000M", "0.002M", "0.004M"]),
        ("k", [0.0, 5e4, 1e5, 1.5e5], ["0k", "50k", "100k", "150k"]),
        ("k", [0.0, 500.0, 1000.0], ["0.0k", "0.5k", "1.0k"]),
        ("", [0.0, 0.25, 0.5], ["0.00", "0.25", "0.50"]),
        (None, [1e3, 1.5e3, 2e3], ["1.0k", "1.5k", "2.0k"]),  # was 1k, 2k, 2k
        (None, [0.0, 0.5, 1.0, 1.5], ["0.0", "0.5", "1.0", "1.5"]),  # was 0, 0, 1, 2
        (None, [-1e5, 0.0, 1e6, 1.25e6], ["-100k", "0", "1.00M", "1.25M"]),
    ],
)
def test_money_labels_get_the_decimals_they_need(
    prefix: str | None, ticks: list[float], expected: list[str]
) -> None:
    assert style.MoneyFormatter(prefix).format_ticks(ticks) == expected


@pytest.mark.parametrize("top", [0.3, 7.0, 45.0, 950.0, 2.9e4, 2.87e5, 1.2e6, 3.3e7])
def test_neighbouring_ticks_never_share_a_label(top: float) -> None:
    # compact (sweep figures); one prefix for the axis (exceedance curves);
    # millions on an axis that has at most six decimals of millions
    prefixes = [None, style.money_prefix(top), *(["M"] if top >= 1e4 else [])]
    for prefix in prefixes:
        for lo in (0.0, -top / 3, top / 2):
            labels = axis_labels(style.MoneyFormatter(prefix), lo, top)
            assert len(labels) >= 2
            assert len(set(labels)) == len(labels), (prefix, lo, top, labels)


def test_money_labels_have_no_negative_zero_and_no_nan() -> None:
    formatter = style.MoneyFormatter("M")
    assert formatter.format_ticks([-1e-9, 0.0, 1e6]) == ["0.0M", "0.0M", "1.0M"]
    assert formatter(float("nan")) == ""
    assert formatter(float("inf")) == ""
    assert style.MoneyFormatter()(-0.4) == "0"  # no locations: no decimals


def test_money_labels_without_locations_use_the_fewest_decimals() -> None:
    formatter = style.MoneyFormatter()
    assert [formatter(v) for v in (1.25e6, 2.5e4, 7.0)] == ["1.2M", "25k", "7"]


def test_money_labels_that_cannot_be_exact_stay_distinct() -> None:
    ticks = [1.0 / 3.0, 2.0 / 3.0, 1.0 / 3.0 + 1e-6]
    labels = style.MoneyFormatter("").format_ticks(ticks)
    assert labels == ["0.333333", "0.666667", "0.333334"]
    same = style.MoneyFormatter("").format_ticks([1.0 / 3.0, 1.0 / 3.0 + 1e-12])
    assert same == ["0.333333", "0.333333"]  # beyond the most decimals


def test_money_prefix() -> None:
    assert [style.money_prefix(v) for v in (2e6, -1e6, 999_999.0, 1e3, 999.0)] == [
        "M",
        "M",
        "k",
        "k",
        "",
    ]
    assert style.money_prefix(float("nan")) == ""
    with pytest.raises(ValueError, match="unknown money prefix 'G'"):
        style.MoneyFormatter("G")
