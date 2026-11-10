"""Tests for ``scripts/build_eberenz_basins.py`` (MAR-132).

The lookup rule on a tiny synthetic IBTrACS-like dataset: exact IDs, IDs
matched by genesis date and position, and the loud failures.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest
import xarray as xr

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_eberenz_basins.py"


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_eberenz_basins", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _ibtracs(
    storms: list[tuple[str, str, list[str], list[float], list[float]]],
) -> xr.Dataset:
    """A dataset with ``sid``, ``name``, ``basin``, ``lat``, ``lon`` per storm."""
    n_time = max(len(s[2]) for s in storms)
    basin = np.full((len(storms), n_time), b"", dtype="S2")
    lat = np.full((len(storms), n_time), np.nan)
    lon = np.full((len(storms), n_time), np.nan)
    for i, (_, _, b, la, lo) in enumerate(storms):
        basin[i, : len(b)] = [x.encode() for x in b]
        lat[i, : len(la)] = la
        lon[i, : len(lo)] = lo
    return xr.Dataset(
        {
            "sid": ("storm", np.array([s[0].encode() for s in storms], dtype="S13")),
            "name": ("storm", np.array([s[1].encode() for s in storms], dtype="S20")),
            "basin": (("storm", "date_time"), basin),
            "lat": (("storm", "date_time"), lat),
            "lon": (("storm", "date_time"), lon),
        }
    )


STORMS = [
    # Iwa: East Pacific, exact ID.
    ("1982324N10193", "IWA", ["EP", "EP"], [10.0, 20.0], [-167.0, -160.0]),
    # Luis: IBTrACS moved its genesis 4 degrees west, so the ID changed.
    ("1995241N11333", "LUIS", ["NA", "NA"], [11.0, 15.0], [-27.0, -40.0]),
    # A storm that starts in one basin and moves into another.
    ("2016269N15165", "CHABA", ["WP", "EP", "WP"], [15.0, 16.0, 17.0], [165, 170, 175]),
]


def test_parse_sid(script: ModuleType) -> None:
    assert script.parse_sid("1982324N10193") == (1982, 324, 10.0, 193.0)
    assert script.parse_sid("2015045S12145") == (2015, 45, -12.0, 145.0)
    for bad in ("1982324X10193", "1982324N1019", "198232AN10193"):
        with pytest.raises(script.BasinLookupError, match="not an IBTrACS"):
            script.parse_sid(bad)


def test_lookup_exact_and_genesis_matches(script: ModuleType) -> None:
    calibration = pd.DataFrame(
        {
            "ibtracsID": [
                "1982324N10193",
                "1995240N11337",
                "2016269N15165",
                "1982324N10193",
            ]
        }
    )
    lookup = script.build_lookup(calibration, _ibtracs(STORMS)).set_index("ibtracsID")
    assert list(lookup.index) == ["1982324N10193", "1995240N11337", "2016269N15165"]
    assert lookup.loc["1982324N10193", "basin"] == "EP"
    assert lookup.loc["1982324N10193", "match"] == "exact"
    luis = lookup.loc["1995240N11337"]
    assert (luis["basin"], luis["match"], luis["ibtracs_sid"]) == (
        "NA",
        "genesis",
        "1995241N11333",
    )
    assert luis["match_distance_deg"] == pytest.approx(
        4.0 * np.cos(np.radians(11)), abs=0.01
    )
    chaba = lookup.loc["2016269N15165"]
    assert (chaba["basin"], chaba["basins_visited"]) == ("WP", "WP;EP")


def test_lookup_fails_loudly(script: ModuleType) -> None:
    far = pd.DataFrame({"ibtracsID": ["1995240N30300"]})  # no storm near it
    with pytest.raises(script.BasinLookupError, match="no IBTrACS storm"):
        script.build_lookup(far, _ibtracs(STORMS))
    odd = [("1982324N10193", "IWA", ["MM"], [10.0], [-167.0])]
    with pytest.raises(script.BasinLookupError, match="not all in"):
        script.build_lookup(
            pd.DataFrame({"ibtracsID": ["1982324N10193"]}), _ibtracs(odd)
        )


def test_main_writes_the_lookup_with_its_source(
    script: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ibtracs = tmp_path / "IBTrACS.test.nc"
    dataset = _ibtracs(STORMS)
    dataset.attrs.update({"date_created": "2025-07-03", "product_version": "v04r01"})
    dataset.to_netcdf(ibtracs)
    calibration = pd.DataFrame({"ibtracsID": ["1982324N10193", "1995240N11337"]})
    monkeypatch.setattr(script, "load_eberenz_edr", lambda: (calibration, "abc"))
    out = tmp_path / "lookup.csv"
    assert script.main(["--ibtracs", str(ibtracs), "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "IBTrACS v04r01" in text
    assert "date_created 2025-07-03" in text
    table = pd.read_csv(out, comment="#", dtype=str, keep_default_na=False)
    assert list(table["basin"]) == ["EP", "NA"]
