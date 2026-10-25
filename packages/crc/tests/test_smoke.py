"""Smoke tests for the CRC adapter package skeleton."""

from importlib.metadata import version
from importlib.resources import files

import parametric_insurance_design as pid
import parametric_insurance_design_crc as pid_crc


def test_version_matches_distribution_metadata() -> None:
    assert pid_crc.__version__ == version("parametric-insurance-design-crc")


def test_ships_py_typed_marker() -> None:
    assert files("parametric_insurance_design_crc").joinpath("py.typed").is_file()


def test_core_is_installed_from_the_workspace() -> None:
    assert pid.__version__ == version("parametric-insurance-design")
