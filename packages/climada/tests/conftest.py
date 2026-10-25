"""Shared fixtures: a tiny synthetic IRIS catalogue and a pipeline config.

CI never downloads IRIS. The catalogue below has five storms in the IRIS text
layout, built so that each pipeline branch is hit:

======== ===== ============================================================
event_id year  role
======== ===== ============================================================
NA_3_0   3     strong hurricane crossing Miami: positive wind and loss
NA_10_1  10    weaker storm passing north of Miami: sorts before NA_3_0
NA_8_0   8     weak storm about 400 km north: within the radius, zero row
NA_7_2   7     a single track point near Miami: skipped (CLIMADA needs 2)
NA_5_0   5     far out in the Atlantic: removed by the proximity filter
======== ===== ============================================================
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

HEADER = "#tcid basin year tc month timestep lon lat vmax pmin rmw r18\n"
N_YEARS = 12

LOCATIONS: list[dict[str, Any]] = [
    {
        "location_id": "L1",
        "lat": 25.7617,
        "lon": -80.1918,
        "value": 1_000_000.0,
        "name": "Brickell",
    },
    {
        "location_id": "L2",
        "lat": 25.7907,
        "lon": -80.13,
        "value": 2_000_000.0,
        "name": "MiamiBeach",
    },
    {
        "location_id": "L3",
        "lat": 25.95,
        "lon": -80.14,
        "value": 500_000.0,
        "name": "Aventura",
    },
]


def _storm(
    tcid: int,
    year: int,
    tc: int,
    lat: np.ndarray,
    lon: np.ndarray,
    vmax: float,
    pmin: float,
) -> list[str]:
    rows = []
    for step, (la, lo) in enumerate(zip(lat, lon, strict=True)):
        rows.append(
            f"{tcid} NA {year} {tc} 9 {step} {lo:.4f} {la:.4f} {vmax:.2f} "
            f"{pmin:.2f} 30.0 250.0\n"
        )
    return rows


def catalogue_text() -> str:
    """The synthetic catalogue, in IRIS file order (by tcid)."""
    lon = np.linspace(-77.0, -83.0, 13)
    rows = [HEADER]
    rows += _storm(30, 3, 0, np.full(13, 25.75), lon, 62.0, 935.0)
    rows += _storm(50, 5, 0, np.full(4, 15.0), np.linspace(-40, -42, 4), 40.0, 960.0)
    rows += _storm(72, 7, 2, np.array([25.6]), np.array([-80.0]), 45.0, 950.0)
    rows += _storm(80, 8, 0, np.full(6, 29.5), np.linspace(-78, -81, 6), 19.0, 1000.0)
    rows += _storm(101, 10, 1, np.full(13, 26.9), lon, 38.0, 975.0)
    return "".join(rows)


@pytest.fixture
def catalogue_path(tmp_path: Path) -> Path:
    path = tmp_path / "iris_tiny.txt"
    path.write_text(catalogue_text(), encoding="utf-8")
    return path


@pytest.fixture
def locations_yaml(tmp_path: Path) -> Path:
    path = tmp_path / "assets.yaml"
    path.write_text(yaml.safe_dump({"locations": LOCATIONS}), encoding="utf-8")
    return path


@pytest.fixture
def config_data(
    catalogue_path: Path, locations_yaml: Path, tmp_path: Path
) -> dict[str, Any]:
    return {
        "catalogue": str(catalogue_path),
        "n_years": N_YEARS,
        "locations": {"yaml": str(locations_yaml)},
        "proximity_km": 500,
        "batch_size": 2,
        "hazard_release": "synthetic test catalogue",
        "output": str(tmp_path / "out"),
    }


@pytest.fixture
def make_config(
    config_data: dict[str, Any],
) -> Callable[..., Any]:
    from parametric_insurance_design_climada.config import parse_config

    def make(**updates: Any) -> Any:  # noqa: ANN401
        return parse_config({**config_data, **updates})

    return make
