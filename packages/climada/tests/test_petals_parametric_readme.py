"""The usage example in ``src/petals_parametric/README.md`` runs (MAR-168).

The README has two code blocks. The first (``<!-- example: climada -->``)
builds the CLIMADA objects from IBTrACS, which needs a download, so here it
is only compiled and its CLIMADA calls are checked to exist. The second
(``<!-- example: design -->``) is run on small synthetic ``tracks``,
``hazard``, ``exposures`` and ``impact``: 40 storms in 30 years near the
README's three sites, nothing downloaded.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from climada.engine import Impact, ImpactCalc
from climada.hazard import Centroids, TCTracks, TropCyclone

from petals_parametric import ParametricCover
from petals_parametric.test._synthetic import (
    exposures,
    hazard_and_impact,
    straight_track,
)

README = Path(__file__).resolve().parents[1] / "src" / "petals_parametric" / "README.md"


def _block(name: str) -> str:
    """Return the Python code block that follows ``<!-- example: name -->``."""
    text = README.read_text(encoding="utf-8")
    found = re.search(
        rf"<!-- example: {name} -->\s*```python\n(.*?)```", text, flags=re.DOTALL
    )
    assert found, f"README has no '{name}' example"
    return found.group(1)


def _synthetic_objects() -> dict[str, Any]:
    """40 straight storms in 1990-2019, some through the sites' circle."""
    rng = np.random.default_rng(20261106)
    years = np.sort(rng.integers(1990, 2020, size=40))
    years[[0, -1]] = [1990, 2019]
    tracks = TCTracks(
        [
            straight_track(
                f"S{i}",
                float(rng.uniform(25.0, 26.8)),
                -77.0,
                -83.0,
                float(rng.uniform(40.0, 150.0)),
                year=int(year),
            )
            for i, year in enumerate(years)
        ]
    )
    exp = exposures()
    hazard, impact = hazard_and_impact(tracks, exp)
    return {"tracks": tracks, "hazard": hazard, "exposures": exp, "impact": impact}


def test_the_climada_block_compiles_and_names_existing_calls() -> None:
    code = _block("climada")
    compile(code, "README climada example", "exec")
    assert callable(TCTracks.from_ibtracs_netcdf)
    assert callable(TCTracks.equal_timestep)
    assert callable(Centroids.from_exposures)
    assert callable(TropCyclone.from_tracks)
    assert callable(ImpactCalc.impact)


def test_the_design_block_runs_on_climada_objects() -> None:
    namespace = _synthetic_objects()
    exec(compile(_block("design"), "README design example", "exec"), namespace)
    for name in ("tail", "joint", "combined"):
        assert isinstance(namespace[name], ParametricCover)
    assert namespace["tail"].scope == "individual"
    assert namespace["combined"].scope == "portfolio"
    metrics = namespace["metrics"]
    assert isinstance(metrics, pd.DataFrame)
    assert metrics["level"].tolist() == ["unit"] * 3 + ["portfolio"]
    assert isinstance(namespace["payouts"], Impact)
    assert namespace["index"].unit == "Saffir-Simpson category"
    # The synthetic storms reach the sites, so the covers are not trivial.
    assert namespace["index"].values.max() >= 1
    assert namespace["combined"].premium > 0
