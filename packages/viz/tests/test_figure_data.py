"""Tests of the figure-data CSV writer (MAR-110)."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from parametric_insurance_design.errors import ParametricInsuranceDesignError
from parametric_insurance_design_viz.errors import FigureDataError
from parametric_insurance_design_viz.figure_data import (
    MAIN_TABLE,
    FigureOutput,
    figure_paths,
    write_figure,
)


def output(name: str = "demo", **data: pd.DataFrame) -> FigureOutput:
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    tables = {MAIN_TABLE: pd.DataFrame({"x": [0.0, 1.0], "y": [0.0, 1.0]})}
    tables.update(data)
    return FigureOutput(name=name, figure=fig, data=tables)


def test_writes_image_and_csvs_next_to_it(tmp_path: Path) -> None:
    out = output(density=pd.DataFrame({"index": [1.5], "density": [0.25]}))
    written = write_figure(out, tmp_path / "figs")
    assert written.name == "demo"
    assert written.image == tmp_path / "figs" / "demo.png"
    assert written.image.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert written.tables == {
        "": tmp_path / "figs" / "demo.csv",
        "density": tmp_path / "figs" / "demo.density.csv",
    }
    pd.testing.assert_frame_equal(pd.read_csv(written.tables[""]), out.data[""])
    assert pd.read_csv(written.tables["density"]).to_dict("list") == {
        "index": [1.5],
        "density": [0.25],
    }
    # no temporary files are left behind
    assert sorted(p.name for p in (tmp_path / "figs").iterdir()) == [
        "demo.csv",
        "demo.density.csv",
        "demo.png",
    ]
    assert not plt.fignum_exists(out.figure.number)


def test_overwrites_and_can_keep_the_figure_open(tmp_path: Path) -> None:
    write_figure(output(), tmp_path)
    out = output()
    out.data[""].loc[0, "y"] = 7.0
    write_figure(out, tmp_path, close=False)
    assert pd.read_csv(tmp_path / "demo.csv")["y"].tolist() == [7.0, 1.0]
    assert plt.fignum_exists(out.figure.number)
    plt.close(out.figure)


@pytest.mark.parametrize("name", ["", "Demo", "_x", "a/b", "a.b", "a b"])
def test_rejects_bad_names(name: str) -> None:
    with pytest.raises(FigureDataError, match="figure name"):
        output(name)
    with pytest.raises(FigureDataError):
        figure_paths(".", name)
    plt.close("all")


def test_requires_main_table_and_dataframes() -> None:
    fig = plt.figure()
    with pytest.raises(FigureDataError, match="no main figure-data table"):
        FigureOutput(name="x", figure=fig, data={"other": pd.DataFrame()})
    with pytest.raises(FigureDataError, match="must be a pandas DataFrame"):
        FigureOutput(name="x", figure=fig, data={"": [1, 2]})  # type: ignore[dict-item]
    with pytest.raises(FigureDataError, match="table key"):
        FigureOutput(
            name="x", figure=fig, data={"": pd.DataFrame(), "Bad.Key": pd.DataFrame()}
        )
    plt.close(fig)


def test_errors_are_library_errors() -> None:
    assert issubclass(FigureDataError, ParametricInsuranceDesignError)
