"""Tests for the per-cell loss path of the pipeline (MAR-114, D2).

A location's loss is the sum of the CLIMADA impacts on its cells; the index
stays at the location. The expectations are independent builds: the same
cells built as locations of their own with the centroid loss (the thesis
path), then summed per location.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml

from parametric_insurance_design_climada.config import (
    CellLossConfig,
    CentroidLossConfig,
    EmanuelVHalfDrawsConfig,
    PipelineConfigError,
    load_config,
    parse_config,
)
from parametric_insurance_design_climada.pipeline import (
    BUILD_RECORD_NAME,
    build_eventset,
    read_cells,
    read_locations,
)

from .conftest import LOCATIONS

PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parents[1]
WHEN = datetime(2026, 10, 27, tzinfo=UTC)
DRAWS = {"kind": "emanuel_v_half", "n_draws": 3, "seed": 7}

#: Cells of the three conftest locations (values sum to theirs), plus one cell
#: in no location.
CELLS: list[dict[str, Any]] = [
    {"lat": 25.7617, "lon": -80.1918, "value": 400_000.0, "location_id": "L1"},
    {"lat": 25.70, "lon": -80.30, "value": 600_000.0, "location_id": "L1"},
    {"lat": 25.7907, "lon": -80.13, "value": 1_500_000.0, "location_id": "L2"},
    {"lat": 25.85, "lon": -80.12, "value": 500_000.0, "location_id": "L2"},
    {"lat": 26.00, "lon": -80.50, "value": 700_000.0, "location_id": None},
    {"lat": 25.95, "lon": -80.14, "value": 500_000.0, "location_id": "L3"},
]


def _write_cells(path: Path, rows: list[dict[str, Any]]) -> Path:
    frame = pd.DataFrame(rows)
    frame["location_id"] = frame["location_id"].astype(object)
    frame.to_parquet(path, index=False)
    return path


@pytest.fixture
def cells_path(tmp_path: Path) -> Path:
    return _write_cells(tmp_path / "cells.parquet", CELLS)


@pytest.fixture
def cells_as_locations(tmp_path: Path) -> Path:
    """The assigned cells as locations of their own (centroid loss)."""
    rows = [
        {
            "location_id": f"C{k}",
            "lat": c["lat"],
            "lon": c["lon"],
            "value": c["value"],
            "name": f"cell {k}",
        }
        for k, c in enumerate(CELLS)
        if c["location_id"] is not None
    ]
    path = tmp_path / "cells_as_locations.yaml"
    path.write_text(yaml.safe_dump({"locations": rows}), encoding="utf-8")
    return path


def _owner_matrix() -> np.ndarray:
    """(n assigned cells, 3) indicator of the cells' locations."""
    owners = [c["location_id"] for c in CELLS if c["location_id"] is not None]
    ids = [str(loc["location_id"]) for loc in LOCATIONS]
    matrix = np.zeros((len(owners), len(ids)))
    for k, owner in enumerate(owners):
        matrix[k, ids.index(owner)] = 1.0
    return matrix


@pytest.mark.parametrize("draws", [None, DRAWS])
def test_loss_is_the_sum_of_independent_cell_losses(
    make_config: Callable[..., Any],
    cells_path: Path,
    cells_as_locations: Path,
    draws: dict[str, Any] | None,
) -> None:
    extra = {} if draws is None else {"vulnerability": draws}
    centroid = build_eventset(make_config(**extra)).eventset
    cells = build_eventset(
        make_config(loss={"kind": "cells", "cells": str(cells_path)}, **extra)
    ).eventset
    per_cell = build_eventset(
        make_config(locations={"yaml": str(cells_as_locations)}, **extra)
    ).eventset
    # Same rows, and the index is still the location's.
    assert cells.events.equals(centroid.events)
    np.testing.assert_array_equal(cells.index, centroid.index)
    # Loss: the cells built as locations (same v_half per event and draw),
    # summed per location.
    np.testing.assert_allclose(
        cells.loss, per_cell.loss @ _owner_matrix(), rtol=1e-12, atol=0.0
    )
    assert cells.loss.max() > 0
    assert not np.allclose(cells.loss, centroid.loss)


def test_one_cell_per_location_reproduces_the_centroid_loss(
    make_config: Callable[..., Any], tmp_path: Path
) -> None:
    rows = [
        {
            "lat": loc["lat"],
            "lon": loc["lon"],
            "value": loc["value"],
            "location_id": loc["location_id"],
        }
        for loc in LOCATIONS
    ]
    path = _write_cells(tmp_path / "same.parquet", rows)
    for extra in ({}, {"vulnerability": DRAWS}):
        centroid = build_eventset(make_config(**extra)).eventset
        cells = build_eventset(
            make_config(loss={"kind": "cells", "cells": str(path)}, **extra)
        ).eventset
        np.testing.assert_array_equal(cells.index, centroid.index)
        np.testing.assert_array_equal(cells.loss, centroid.loss)
        assert cells.content_hash() != centroid.content_hash()


def test_split_cells_at_one_point_keep_the_loss(
    make_config: Callable[..., Any], tmp_path: Path
) -> None:
    rows = [
        {
            "lat": loc["lat"],
            "lon": loc["lon"],
            "value": share * loc["value"],
            "location_id": loc["location_id"],
        }
        for loc in LOCATIONS
        for share in (0.25, 0.75)
    ]
    path = _write_cells(tmp_path / "split.parquet", rows)
    centroid = build_eventset(make_config(vulnerability=DRAWS)).eventset
    cells = build_eventset(
        make_config(loss={"kind": "cells", "cells": str(path)}, vulnerability=DRAWS)
    ).eventset
    np.testing.assert_allclose(cells.loss, centroid.loss, rtol=1e-12, atol=0.0)


def test_cell_build_records_its_inputs(
    make_config: Callable[..., Any], cells_path: Path
) -> None:
    config = make_config(
        loss={"kind": "cells", "cells": str(cells_path), "unit": "USD (2018)"},
        scenario_notes=["Value unit: a caveat.", "Attribution: someone."],
        licence="CC-BY-4.0",
    )
    es = build_eventset(config, created_at=WHEN).eventset
    meta = es.metadata
    assert meta.loss.unit == "USD (2018)"
    assert meta.loss.currency == "USD"
    assert meta.licence == "CC-BY-4.0"
    assert meta.scenario.endswith("Value unit: a caveat. Attribution: someone.")
    assert "sum of the impacts on its cells (5 cells in all" in meta.scenario
    assert set(meta.provenance.source_checksums) == {
        "iris_tiny.txt",
        "assets.yaml",
        "cells.parquet",
    }
    record = meta.transforms[0]
    assert record.name == BUILD_RECORD_NAME
    loss = record.parameters["loss"]
    assert loss["kind"] == "cells"
    assert loss["file"] == "cells.parquet"
    assert (
        meta.provenance.source_checksums["cells.parquet"] == f"sha256:{loss['sha256']}"
    )
    assert loss["n_cells_file"] == 6
    assert loss["n_cells"] == 5
    assert loss["n_cells_positive"] == 5
    assert loss["n_cells_unassigned"] == 1
    assert loss["value_unassigned"] == 700_000.0
    assert 0 < loss["max_cell_distance_km"] < 15


def test_centroid_loss_is_the_unchanged_default(
    make_config: Callable[..., Any],
) -> None:
    config = make_config()
    assert config.loss == CentroidLossConfig()
    default = build_eventset(config, created_at=WHEN).eventset
    explicit = build_eventset(
        make_config(loss={"kind": "centroid"}, scenario_notes=[]), created_at=WHEN
    ).eventset
    assert explicit.content_hash() == default.content_hash()
    assert "loss" not in default.metadata.transforms[0].parameters
    assert default.metadata.loss.unit == "USD"


def test_batch_size_does_not_change_the_cell_draws(
    make_config: Callable[..., Any], cells_path: Path
) -> None:
    hashes = {
        build_eventset(
            make_config(
                loss={"kind": "cells", "cells": str(cells_path)},
                vulnerability=DRAWS,
                batch_size=size,
            ),
            created_at=WHEN,
        ).eventset.content_hash()
        for size in (1, 2, 500)
    }
    assert len(hashes) == 1


def test_proximity_must_cover_the_cells_reach(
    make_config: Callable[..., Any], cells_path: Path
) -> None:
    with pytest.raises(PipelineConfigError, match="could have wind at a cell"):
        build_eventset(
            make_config(
                loss={"kind": "cells", "cells": str(cells_path)}, proximity_km=300
            )
        )


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda f: f.drop(columns="value"), "lack columns"),
        (lambda f: f.assign(location_id=f["location_id"].replace("L3", "L9")), "L9"),
        (
            lambda f: f[f["location_id"] != "L3"].reset_index(drop=True),
            "without a cell",
        ),
        (lambda f: f.assign(value=f["value"] * 1.001), "do not sum"),
        (lambda f: f.assign(lat=f["lat"].where(f.index != 0, np.nan)), "finite"),
        (lambda f: f.assign(lon=f["lon"].where(f.index != 0, 200.0)), "lon"),
    ],
)
def test_read_cells_rejects_inconsistent_tables(
    tmp_path: Path,
    locations_yaml: Path,
    change: Callable[[pd.DataFrame], pd.DataFrame],
    match: str,
) -> None:
    from parametric_insurance_design_climada.config import LocationsConfig

    locations = read_locations(LocationsConfig(yaml=locations_yaml))
    frame = pd.DataFrame(CELLS)
    frame["location_id"] = frame["location_id"].astype(object)
    path = tmp_path / "bad.parquet"
    change(frame).to_parquet(path, index=False)
    with pytest.raises(PipelineConfigError, match=match):
        read_cells(path, locations)


def test_read_cells_reports_an_unreadable_file(
    tmp_path: Path, locations_yaml: Path
) -> None:
    from parametric_insurance_design_climada.config import LocationsConfig

    locations = read_locations(LocationsConfig(yaml=locations_yaml))
    (tmp_path / "broken.parquet").write_text("not parquet", encoding="utf-8")
    with pytest.raises(PipelineConfigError, match="cannot read cells"):
        read_cells(tmp_path / "broken.parquet", locations)


def test_read_cells_membership_sums_per_location(
    cells_path: Path, locations_yaml: Path
) -> None:
    from parametric_insurance_design_climada.config import LocationsConfig

    locations = read_locations(LocationsConfig(yaml=locations_yaml))
    table = read_cells(cells_path, locations)
    assert table.n_cells == 5
    assert table.cells["location_id"].tolist() == ["L1", "L1", "L2", "L2", "L3"]
    np.testing.assert_array_equal(table.membership.toarray(), _owner_matrix())
    np.testing.assert_allclose(
        table.cells["value"].to_numpy() @ table.membership,
        locations["value"].to_numpy(),
    )


def test_cells_path_resolves_against_the_config_directory(tmp_path: Path) -> None:
    config = parse_config(
        {
            "catalogue": "iris.txt",
            "n_years": 10,
            "locations": {"yaml": "a.yaml"},
            "loss": {"kind": "cells", "cells": "sub/cells.parquet"},
            "output": "out",
        },
        base_dir=tmp_path,
    )
    assert isinstance(config.loss, CellLossConfig)
    assert config.loss.cells == (tmp_path / "sub" / "cells.parquet").resolve()


@pytest.mark.parametrize(
    ("loss", "match"),
    [
        ({"kind": "cells"}, "cells"),
        ({"kind": "grid", "cells": "c.parquet"}, "kind"),
        ({"kind": "cells", "cells": "c.parquet", "unit": ""}, "unit"),
        ({"kind": "centroid", "cells": "c.parquet"}, "cells"),
    ],
)
def test_invalid_loss_configs_are_rejected(
    config_data: dict[str, Any], loss: dict[str, Any], match: str
) -> None:
    with pytest.raises(PipelineConfigError, match=match):
        parse_config({**config_data, "loss": loss})


def test_empty_scenario_note_is_rejected(config_data: dict[str, Any]) -> None:
    with pytest.raises(PipelineConfigError, match="scenario_notes"):
        parse_config({**config_data, "scenario_notes": [""]})


@pytest.mark.parametrize(
    ("name", "index_kind"),
    [
        ("florida_counties.yaml", "centroid_wind"),
        ("florida_counties_cat_in_circle.yaml", "cat_in_circle"),
    ],
)
def test_florida_configs_load(name: str, index_kind: str) -> None:
    config = load_config(PACKAGE / "configs" / name)
    assert config.index.kind == index_kind
    assert isinstance(config.loss, CellLossConfig)
    assert config.loss.cells == (
        REPO / "data" / "litpop-florida" / "locations" / "cells.parquet"
    )
    assert config.loss.unit == "USD (LitPop reference_year 2018)"
    assert config.locations.yaml == (
        REPO / "data" / "litpop-florida" / "locations" / "locations.yaml"
    )
    assert config.licence == "CC-BY-4.0"
    assert isinstance(config.vulnerability, EmanuelVHalfDrawsConfig)
    assert config.vulnerability.n_draws == 10
    assert config.vulnerability.prior.kind == "eberenz2021_edr"
    assert config.vulnerability.prior.wind_only is True
    notes = " ".join(config.scenario_notes)
    for text in ("LitPop", "CC BY 4.0", "TIGER/Line", "IRIS", "reference_year 2018"):
        assert text in notes


def test_florida_configs_differ_only_in_index_and_output() -> None:
    a = load_config(PACKAGE / "configs" / "florida_counties.yaml")
    b = load_config(PACKAGE / "configs" / "florida_counties_cat_in_circle.yaml")
    assert a.model_copy(update={"index": b.index, "output": b.output}) == b
