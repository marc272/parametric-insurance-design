"""Write a figure together with its figure-data CSV (SPEC §7 F-08).

Every figure of this package is returned as a
:class:`FigureOutput`: the matplotlib figure plus the tables it was drawn
from. :func:`write_figure` saves the image and, next to it, one CSV per
table, so every plotted number can be checked and re-plotted without the
image:

::

    <out_dir>/<name>.png            the image
    <out_dir>/<name>.csv            the main figure data (key "")
    <out_dir>/<name>.<part>.csv     further tables, e.g. "density"

Tables are tidy (one row per plotted value) and carry the ``run_id`` of the
result they come from wherever there is one.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.figure import Figure

from parametric_insurance_design_viz.errors import FigureDataError

__all__ = [
    "DEFAULT_DPI",
    "IMAGE_SUFFIX",
    "MAIN_TABLE",
    "FigureOutput",
    "WrittenFigure",
    "figure_paths",
    "write_figure",
]

MAIN_TABLE: Final[str] = ""
"""Key of the main figure-data table, written to ``<name>.csv``."""

IMAGE_SUFFIX: Final[str] = ".png"
"""Image format of written figures."""

DEFAULT_DPI: Final[int] = 150
"""Resolution of written images (thesis ``save_plot_outputs``)."""

_NAME: Final[re.Pattern[str]] = re.compile(r"[a-z0-9][a-z0-9_\-]*")


def _check_name(value: str, what: str) -> None:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise FigureDataError(
            f"{what} must be lowercase letters, digits, '_' or '-', not "
            f"starting with '_' or '-', got {value!r}"
        )


@dataclass(frozen=True, eq=False)
class FigureOutput:
    """A drawn figure and the tables it shows.

    Parameters
    ----------
    name : str
        File stem: lowercase letters, digits, ``_`` and ``-``.
    figure : matplotlib.figure.Figure
        The figure.
    data : mapping of str to pandas.DataFrame
        The figure data. Must hold the main table under :data:`MAIN_TABLE`
        (``""``); other keys name further tables.

    Raises
    ------
    FigureDataError
        If the name or a table key is invalid, a table is not a DataFrame, or
        the main table is missing.
    """

    name: str
    figure: Figure
    data: Mapping[str, pd.DataFrame] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate the name and the tables."""
        _check_name(self.name, "a figure name")
        data = dict(self.data)
        if MAIN_TABLE not in data:
            raise FigureDataError(
                f"figure {self.name!r} has no main figure-data table (key '')"
            )
        for key, table in data.items():
            if key != MAIN_TABLE:
                _check_name(key, f"table key of figure {self.name!r}")
            if not isinstance(table, pd.DataFrame):
                raise FigureDataError(
                    f"figure {self.name!r}: table {key!r} must be a pandas "
                    f"DataFrame, got {type(table).__name__}"
                )
        object.__setattr__(self, "data", data)


@dataclass(frozen=True)
class WrittenFigure:
    """Files written for one figure.

    Parameters
    ----------
    name : str
        The figure's name.
    image : pathlib.Path
        The image file.
    tables : mapping of str to pathlib.Path
        One CSV per table key.
    """

    name: str
    image: Path
    tables: Mapping[str, Path]


def figure_paths(
    out_dir: str | Path, name: str, keys: tuple[str, ...] = (MAIN_TABLE,)
) -> tuple[Path, dict[str, Path]]:
    """Return the image path and the CSV path per table key of a figure.

    Parameters
    ----------
    out_dir : str or pathlib.Path
        Output directory.
    name : str
        Figure name.
    keys : tuple of str, default ("",)
        Table keys.

    Returns
    -------
    tuple
        ``(image path, {key: csv path})``.

    Raises
    ------
    FigureDataError
        If the name or a key is invalid.
    """
    _check_name(name, "a figure name")
    directory = Path(out_dir)
    tables: dict[str, Path] = {}
    for key in keys:
        if key == MAIN_TABLE:
            tables[key] = directory / f"{name}.csv"
        else:
            _check_name(key, f"table key of figure {name!r}")
            tables[key] = directory / f"{name}.{key}.csv"
    return directory / f"{name}{IMAGE_SUFFIX}", tables


def _replace_into(path: Path, write: Callable[[Path], object]) -> None:
    """Call ``write(tmp)`` and move the temporary file to ``path``."""
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        write(tmp)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write_figure(
    output: FigureOutput,
    out_dir: str | Path,
    *,
    dpi: int = DEFAULT_DPI,
    close: bool = True,
) -> WrittenFigure:
    """Save a figure as PNG and its figure data as CSV next to it.

    Each file is written to a temporary name first and then moved into
    place, so an interrupted write leaves no half-written file under the
    final name. Existing files of the same figure are replaced.

    Parameters
    ----------
    output : FigureOutput
        The figure and its tables.
    out_dir : str or pathlib.Path
        Output directory; created if missing.
    dpi : int, default :data:`DEFAULT_DPI`
        Image resolution.
    close : bool, default True
        Close the figure after saving (frees its memory in batch runs).

    Returns
    -------
    WrittenFigure
        The paths written.
    """
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    image, tables = figure_paths(directory, output.name, tuple(output.data))
    try:
        _replace_into(
            image,
            lambda tmp: output.figure.savefig(
                tmp, format="png", dpi=dpi, bbox_inches="tight"
            ),
        )
        for key, path in tables.items():
            frame = output.data[key]
            _replace_into(path, lambda tmp, frame=frame: frame.to_csv(tmp, index=False))
    finally:
        if close:
            plt.close(output.figure)
    return WrittenFigure(name=output.name, image=image, tables=tables)
