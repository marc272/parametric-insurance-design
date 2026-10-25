"""Smoke tests for the CLIMADA adapter package and its pixi environment.

They check that the pixi env holds CLIMADA, the core (from ``../core``) and
this package, at versions the core accepts, and that it holds no CRC code.
"""

import importlib.util
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
from pathlib import Path

import pytest
import scipy

import parametric_insurance_design as pid
import parametric_insurance_design_climada as pid_climada

CORE_SRC = Path(__file__).resolve().parents[2] / "core" / "src"


def _release(dist_version: str) -> tuple[int, ...]:
    """Return the leading numeric release components of a version string."""
    parts: list[int] = []
    for part in dist_version.split("."):
        if not part.isdigit():
            break
        parts.append(int(part))
    return tuple(parts)


def test_version_matches_distribution_metadata() -> None:
    assert pid_climada.__version__ == version("parametric-insurance-design-climada")


def test_ships_py_typed_marker() -> None:
    assert files("parametric_insurance_design_climada").joinpath("py.typed").is_file()


def test_core_is_installed_editable_from_the_repository() -> None:
    assert pid.__version__ == version("parametric-insurance-design")
    assert pid.__file__ is not None
    assert Path(pid.__file__).resolve().is_relative_to(CORE_SRC)


def test_climada_imports_with_the_classes_the_adapter_needs() -> None:
    from climada.engine import ImpactCalc
    from climada.entity import Exposures, ImpactFuncSet
    from climada.entity.impact_funcs.trop_cyclone import ImpfTropCyclone
    from climada.hazard import Centroids, TCTracks, TropCyclone

    assert _release(version("climada"))[:1] == (6,)
    for cls in (
        ImpactCalc,
        Exposures,
        ImpactFuncSet,
        ImpfTropCyclone,
        Centroids,
        TCTracks,
        TropCyclone,
    ):
        assert isinstance(cls, type)


def test_scipy_meets_the_core_floor() -> None:
    # The core needs scipy >= 1.15: fcluster(maxclust) is broken on 1.11-1.14.
    assert _release(scipy.__version__)[:2] >= (1, 15)


def test_the_env_holds_no_crc_code() -> None:
    # The CLIMADA stream is CRC-free (AGENTS.md): the CRC adapter must not even
    # be installed here, so nothing in this package can import it.
    assert importlib.util.find_spec("parametric_insurance_design_crc") is None
    with pytest.raises(PackageNotFoundError):
        version("parametric-insurance-design-crc")
