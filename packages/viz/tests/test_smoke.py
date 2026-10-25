"""Smoke tests for the viz package skeleton."""

from importlib.metadata import version
from importlib.resources import files

import parametric_insurance_design as pid
import parametric_insurance_design_viz as pid_viz


def test_version_matches_distribution_metadata() -> None:
    assert pid_viz.__version__ == version("parametric-insurance-design-viz")


def test_ships_py_typed_marker() -> None:
    assert files("parametric_insurance_design_viz").joinpath("py.typed").is_file()


def test_core_is_installed_from_the_workspace() -> None:
    assert pid.__version__ == version("parametric-insurance-design")
