"""Smoke tests for the core package skeleton."""

from importlib.metadata import version
from importlib.resources import files

import numpy as np
import pandas as pd

import parametric_insurance_design as pid


def test_version_matches_distribution_metadata() -> None:
    assert isinstance(pid.__version__, str)
    assert pid.__version__ == version("parametric-insurance-design")


def test_ships_py_typed_marker() -> None:
    assert files("parametric_insurance_design").joinpath("py.typed").is_file()


def test_declared_dependencies_work_together() -> None:
    # Guards the declared floors (numpy>=1.26, pandas>=2.1): CI also runs this
    # with the lowest direct versions on Python 3.11.
    frame = pd.DataFrame({"loss": np.arange(4, dtype=np.float64)})
    assert float(frame["loss"].to_numpy().sum()) == 6.0
