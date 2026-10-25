"""Tests of the cat-in-a-circle index builder (MAR-26, SPEC §6.3 index (b)).

Expected values are worked out by hand from the synthetic catalogue in
``conftest.py``: ``NA_3_0`` runs along latitude 25.75 from 77 to 83 W with
track points 0.5 degrees (about 50 km) apart and ``vmax`` 62 m/s (120.5 kn,
category 4); ``NA_10_1`` runs along 26.9 N at 38 m/s (73.9 kn, category 1),
105.6 km from L3, 123.4 km from L2 and 126.6 km from L1; ``NA_8_0`` runs along
29.5 N at 19 m/s (category 0), about 400 km from the assets. L1 lies 1.3 km,
L2 4.5 km and L3 22.2 km from ``NA_3_0``'s path.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from climada.hazard.tc_tracks import SAFFIR_SIM_CAT
from numpy.typing import NDArray

from parametric_insurance_design.errors import ComponentConfigError
from parametric_insurance_design.eventset import TransformRecord
from parametric_insurance_design_climada.cat_in_circle import (
    SAFFIR_SIMPSON_KN,
    CatInCircleIndex,
    category_of,
    densify_track,
    max_wind_within_radius,
)
from parametric_insurance_design_climada.config import (
    CatInCircleIndexConfig,
    CentroidWindIndexConfig,
    PipelineConfigError,
    load_config,
)
from parametric_insurance_design_climada.hooks import (
    CentroidWindIndex,
    HazardBatch,
    IndexBuilder,
    NoDraws,
    VulnerabilityDraws,
)
from parametric_insurance_design_climada.pipeline import (
    BUILD_RECORD_NAME,
    build_eventset,
    make_index_builder,
)
from parametric_insurance_design_climada.tracks import MS_TO_KT, haversine_km

from .conftest import N_YEARS

PACKAGE = Path(__file__).resolve().parents[1]
MODELLED = ["NA_10_1", "NA_3_0", "NA_8_0"]
WHEN = datetime(2026, 10, 25, tzinfo=UTC)


# -- categories ------------------------------------------------------------


def test_default_breakpoints_are_climadas_saffir_simpson_scale() -> None:
    assert SAFFIR_SIMPSON_KN == tuple(float(v) for v in SAFFIR_SIM_CAT[1:6])


def test_category_counts_the_breakpoints_reached() -> None:
    wind = np.array([0.0, 63.99, 64.0, 82.9, 83.0, 96.0, 112.9, 113.0, 136.9, 137.0])
    expected = [0, 0, 1, 1, 2, 3, 3, 4, 4, 5]
    np.testing.assert_array_equal(category_of(wind, SAFFIR_SIMPSON_KN), expected)
    assert category_of(np.array([500.0]), SAFFIR_SIMPSON_KN).dtype == np.float64


def test_category_agrees_with_climadas_rule_clipped_at_zero() -> None:
    wind = np.random.default_rng(0).uniform(0, 180, 2000)
    # CLIMADA (TCTracks readers): category = argmax(wind < SAFFIR_SIM_CAT) - 1,
    # with -1 for tropical depressions and 0 for tropical storms.
    climada = np.argmax(wind[:, None] < np.array(SAFFIR_SIM_CAT)[None], axis=1) - 1
    np.testing.assert_array_equal(
        category_of(wind, SAFFIR_SIMPSON_KN), np.maximum(climada, 0)
    )


# -- track interpolation ---------------------------------------------------


def test_densify_keeps_the_points_and_interpolates_linearly() -> None:
    lat = np.array([20.0, 21.0, 23.0])
    lon = np.array([-70.0, -71.0, -71.0])
    wind = np.array([60.0, 90.0, 30.0])
    hours = np.array([0.0, 3.0, 6.0])
    dlat, dlon, dwind = densify_track(lat, lon, wind, hours, 0.5)
    assert len(dlat) == 2 * 6 + 1
    np.testing.assert_array_equal(dlat[[0, 6, 12]], lat)
    np.testing.assert_array_equal(dlon[[0, 6, 12]], lon)
    np.testing.assert_array_equal(dwind[[0, 6, 12]], wind)
    np.testing.assert_allclose(dlat[:7], np.linspace(20, 21, 7), rtol=0, atol=1e-12)
    np.testing.assert_allclose(dwind[6:], np.linspace(90, 30, 7), rtol=0, atol=1e-12)
    np.testing.assert_allclose(dlon[6:], -71.0, rtol=0, atol=0)


def test_densify_splits_each_segment_by_its_own_duration() -> None:
    hours = np.array([0.0, 1.0, 3.0])
    out = densify_track(np.zeros(3), np.zeros(3), np.zeros(3), hours, 0.75)
    # ceil(1 / 0.75) = 2 parts, ceil(2 / 0.75) = 3 parts, plus the last point.
    assert len(out[0]) == 2 + 3 + 1


def test_densify_without_a_step_returns_the_points() -> None:
    lat, lon, wind = np.array([1.0, 2.0]), np.array([3.0, 4.0]), np.array([5.0, 6.0])
    out = densify_track(lat, lon, wind, np.array([0.0, 3.0]), None)
    for got, given in zip(out, (lat, lon, wind), strict=True):
        np.testing.assert_array_equal(got, given)
    single = densify_track(lat[:1], lon[:1], wind[:1], np.array([0.0]), 0.5)
    assert len(single[0]) == 1


def test_densify_crosses_the_antimeridian_the_short_way() -> None:
    _, lon, _ = densify_track(
        np.zeros(2), np.array([179.0, -179.0]), np.zeros(2), np.array([0.0, 3.0]), 1.5
    )
    np.testing.assert_allclose(lon, [179.0, 180.0, 181.0])


def test_densify_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="same length"):
        densify_track(np.zeros(2), np.zeros(3), np.zeros(2), np.zeros(2), 0.5)
    with pytest.raises(ValueError, match="increase"):
        densify_track(np.zeros(2), np.zeros(2), np.zeros(2), np.array([3.0, 3.0]), 0.5)


# -- distance --------------------------------------------------------------


def test_max_wind_within_radius_is_inclusive_and_zero_outside() -> None:
    lat = np.array([25.0, 25.0, 25.0])
    lon = np.array([-80.0, -80.2, -80.4])
    wind = np.array([100.0, 80.0, 120.0])
    loc_lat = np.array([25.0, 25.0, 40.0])
    loc_lon = np.array([-80.0, -80.4, -80.0])
    d = haversine_km(lat, lon, 25.0, -80.0)
    # Location 0: radius exactly to the second point, so points 0 and 1 count.
    out = max_wind_within_radius(lat, lon, wind, loc_lat, loc_lon, float(d[1]))
    np.testing.assert_array_equal(out, [100.0, 120.0, 0.0])
    out = max_wind_within_radius(lat, lon, wind, loc_lat, loc_lon, float(d[2]))
    np.testing.assert_array_equal(out, [120.0, 120.0, 0.0])


# -- builder parameters ----------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"radius_km": 0.0}, "radius_km"),
        ({"radius_km": float("nan")}, "radius_km"),
        ({"radius_km": 50.0, "metric": "wind"}, "metric"),
        ({"radius_km": 50.0, "breakpoints_kn": ()}, "breakpoints_kn"),
        ({"radius_km": 50.0, "breakpoints_kn": (64.0, 64.0)}, "breakpoints_kn"),
        ({"radius_km": 50.0, "breakpoints_kn": (83.0, 64.0)}, "breakpoints_kn"),
        ({"radius_km": 50.0, "breakpoints_kn": (-1.0, 64.0)}, "breakpoints_kn"),
        ({"radius_km": 50.0, "track_step_hours": 0.0}, "track_step_hours"),
    ],
)
def test_invalid_builder_parameters_are_rejected(
    kwargs: dict[str, Any], match: str
) -> None:
    with pytest.raises(ComponentConfigError, match=match):
        CatInCircleIndex(**kwargs)


def test_builder_describes_itself_and_records_its_parameters() -> None:
    builder = CatInCircleIndex(radius_km=50)
    assert isinstance(builder, IndexBuilder)
    definition = builder.describe("CLIMADA wind field (unused)")
    assert definition.definition.startswith("cat_in_circle(r=50 km, metric=category)")
    assert "64, 83, 96, 113, 137" in definition.definition
    assert "1-minute sustained" in definition.definition
    assert "0.5 h" in definition.definition
    assert "CLIMADA wind field" not in definition.definition
    assert definition.unit == "Saffir-Simpson category"
    params = builder.parameters()
    assert params["kind"] == "cat_in_circle"
    assert params["radius_km"] == 50
    assert params["breakpoints_kn"] == list(SAFFIR_SIMPSON_KN)
    assert "NHC" in params["breakpoint_source"]
    assert params["track_step_hours"] == 0.5
    json.dumps(params)

    custom = CatInCircleIndex(
        radius_km=30, breakpoints_kn=(50, 100), track_step_hours=None
    )
    assert custom.breakpoints_kn == (50.0, 100.0)
    assert custom.describe("").unit == "category"
    assert "custom breakpoints [50, 100] kn" in custom.describe("").definition
    assert "track points as given" in custom.describe("").definition
    assert custom.parameters()["breakpoint_source"] == "custom"

    wind = CatInCircleIndex(radius_km=30, metric="max_wind").describe("")
    assert wind.unit == "m/s"
    assert wind.definition.startswith("cat_in_circle(r=30 km, metric=max_wind)")


# -- config ----------------------------------------------------------------


def test_index_section_selects_the_builder(make_config: Callable[..., Any]) -> None:
    default = make_config()
    assert default.index == CentroidWindIndexConfig()
    assert make_index_builder(default) == CentroidWindIndex()
    config = make_config(
        index={
            "kind": "cat_in_circle",
            "radius_km": 30,
            "metric": "max_wind",
            "breakpoints_kn": [60, 90],
            "track_step_hours": None,
        }
    )
    assert isinstance(config.index, CatInCircleIndexConfig)
    assert make_index_builder(config) == CatInCircleIndex(
        radius_km=30, metric="max_wind", breakpoints_kn=(60, 90), track_step_hours=None
    )
    assert make_index_builder(
        make_config(index={"kind": "cat_in_circle", "radius_km": 50})
    ) == CatInCircleIndex(radius_km=50)


@pytest.mark.parametrize(
    ("index", "match"),
    [
        ({"kind": "cat_in_circle"}, "radius_km"),
        ({"kind": "cat_in_circle", "radius_km": 0}, "radius_km"),
        ({"kind": "cat_in_circle", "radius_km": 251}, "half of proximity_km"),
        ({"kind": "cat_in_circle", "radius_km": 50, "radius": 50}, "radius"),
        ({"kind": "cat_in_circle", "radius_km": 50, "metric": "x"}, "metric"),
        (
            {"kind": "cat_in_circle", "radius_km": 50, "breakpoints_kn": [83, 64]},
            "strictly",
        ),
        ({"kind": "cat_in_circle", "radius_km": 50, "track_step_hours": 0}, "track"),
        ({"kind": "circle", "radius_km": 50}, "kind|tag"),
        ({"kind": "centroid_wind", "radius_km": 50}, "radius_km"),
    ],
)
def test_invalid_index_sections_are_rejected(
    make_config: Callable[..., Any], index: dict[str, Any], match: str
) -> None:
    with pytest.raises(PipelineConfigError, match=match):
        make_config(index=index)


def test_example_config_selects_cat_in_circle() -> None:
    config = load_config(PACKAGE / "configs" / "thesis_cat_in_circle.yaml")
    thesis = load_config(PACKAGE / "configs" / "thesis.yaml")
    assert make_index_builder(config) == CatInCircleIndex(radius_km=50)
    # Everything but the index and the output is the thesis build's.
    same = {"index", "output"}
    assert config.model_dump(exclude=same) == thesis.model_dump(exclude=same)
    assert config.output != thesis.output


# -- pipeline end to end ---------------------------------------------------


def _build(make_config: Callable[..., Any], **index: Any) -> Any:  # noqa: ANN401
    config = make_config(index={"kind": "cat_in_circle", **index})
    return build_eventset(config, created_at=WHEN).eventset


def test_pipeline_writes_the_category_within_the_circle(
    make_config: Callable[..., Any],
) -> None:
    es = _build(make_config, radius_km=30)
    assert es.events["event_id"].tolist() == MODELLED
    np.testing.assert_array_equal(es.index, [[0, 0, 0], [4, 4, 4], [0, 0, 0]])
    # r = 110 km reaches NA_10_1 (category 1) from L3 only; 150 km from all.
    np.testing.assert_array_equal(
        _build(make_config, radius_km=110).index, [[0, 0, 1], [4, 4, 4], [0, 0, 0]]
    )
    np.testing.assert_array_equal(
        _build(make_config, radius_km=150).index, [[1, 1, 1], [4, 4, 4], [0, 0, 0]]
    )


def test_interpolation_catches_storms_between_track_points(
    make_config: Callable[..., Any],
) -> None:
    # NA_3_0's raw points are about 50 km apart; the nearest ones are 19 km
    # (L1) and 14 km (L2) away, so a 10 km circle misses them. Interpolated to
    # 0.5 h (about 8 km apart), the track passes within 3 km (L1) and 6 km
    # (L2). L3 is 22 km off the path either way.
    raw = _build(make_config, radius_km=10, track_step_hours=None)
    np.testing.assert_array_equal(raw.index, np.zeros((3, 3)))
    fine = _build(make_config, radius_km=10)
    np.testing.assert_array_equal(fine.index, [[0, 0, 0], [4, 4, 0], [0, 0, 0]])


def test_max_wind_metric_is_the_track_wind_in_m_s(
    make_config: Callable[..., Any],
) -> None:
    es = _build(make_config, radius_km=250, metric="max_wind")
    np.testing.assert_allclose(es.index[0], 38.0, rtol=1e-12)
    np.testing.assert_allclose(es.index[1], 62.0, rtol=1e-12)
    # NA_8_0 stays about 400 km away: no track point in the circle.
    np.testing.assert_array_equal(es.index[2], 0.0)
    assert es.metadata.index.unit == "m/s"
    cat = _build(make_config, radius_km=250)
    np.testing.assert_array_equal(
        cat.index, category_of(es.index * MS_TO_KT, SAFFIR_SIMPSON_KN)
    )


def test_cat_in_circle_changes_the_index_only(
    make_config: Callable[..., Any],
) -> None:
    base = build_eventset(make_config(), created_at=WHEN).eventset
    es = _build(make_config, radius_km=50)
    np.testing.assert_array_equal(es.loss, base.loss)
    assert es.events.equals(base.events)
    assert es.metadata.index.definition.startswith("cat_in_circle(r=50 km")
    assert es.metadata.index.unit == "Saffir-Simpson category"
    (record,) = es.metadata.transforms
    assert record.name == BUILD_RECORD_NAME
    assert record.parameters["index"] == CatInCircleIndex(radius_km=50).parameters()
    assert es.content_hash() != base.content_hash()
    assert es.content_hash() != _build(make_config, radius_km=60).content_hash()


def test_explicit_builder_replaces_the_config_and_is_checked(
    make_config: Callable[..., Any],
) -> None:
    config = make_config(index={"kind": "cat_in_circle", "radius_km": 30})
    es = build_eventset(config, index_builder=CentroidWindIndex()).eventset
    assert es.metadata.transforms[0].parameters["index"] == {"kind": "centroid_wind"}
    with pytest.raises(PipelineConfigError, match="half of proximity_km"):
        build_eventset(make_config(), index_builder=CatInCircleIndex(radius_km=300))


def test_default_path_is_unchanged(make_config: Callable[..., Any]) -> None:
    # The default config (no index section) builds exactly what the thesis
    # builder gives when passed explicitly, as before MAR-26; the parity
    # comparison on the IRIS catalogue is in the PR (bit-identical index and
    # loss, same content hash as MAR-73).
    default = build_eventset(make_config(), created_at=WHEN).eventset
    explicit = build_eventset(
        make_config(index={"kind": "centroid_wind"}),
        index_builder=CentroidWindIndex(),
        created_at=WHEN,
    ).eventset
    assert default.content_hash() == explicit.content_hash()
    assert default.metadata.transforms[0].parameters["index"] == {
        "kind": "centroid_wind"
    }
    assert default.metadata.index.unit == "m/s"
    assert default.metadata.index.definition.startswith(
        "Maximum 1-minute sustained wind speed"
    )


# -- composition with vulnerability draws (MAR-25) -------------------------


@dataclass(frozen=True)
class StubDraws:
    """A stub vulnerability hook: three draws scaling the base loss."""

    factors: tuple[float, ...] = (0.5, 1.0, 2.0)

    @property
    def n_draws(self) -> int:
        return len(self.factors)

    def record(self, *, n_filters_before: int) -> TransformRecord | None:
        return TransformRecord(
            name="vulnerability_draws",
            function="tests.StubDraws",
            version="0",
            n_filters_before=n_filters_before,
            parameters={"factors": list(self.factors)},
        )

    def losses(
        self,
        batch: HazardBatch,
        base_loss: NDArray[np.float64],
        rng: np.random.Generator | None,
    ) -> NDArray[np.float64]:
        assert rng is not None
        return np.stack([f * base_loss for f in self.factors])


@pytest.mark.parametrize(
    "builder", [CentroidWindIndex(), CatInCircleIndex(radius_km=50)]
)
def test_index_builders_compose_with_vulnerability_draws(
    make_config: Callable[..., Any], builder: IndexBuilder
) -> None:
    assert isinstance(StubDraws(), VulnerabilityDraws)
    base = build_eventset(
        make_config(), index_builder=builder, vulnerability=NoDraws()
    ).eventset
    es = build_eventset(
        make_config(),
        index_builder=builder,
        vulnerability=StubDraws(),
        rng=np.random.default_rng(0),
    ).eventset
    n = StubDraws().n_draws
    assert es.n_rows == n * base.n_rows
    assert es.events["event_id"].tolist() == [e for e in MODELLED for _ in range(n)]
    assert es.events["draw_id"].tolist() == list(range(n)) * len(MODELLED)
    np.testing.assert_allclose(es.rates, np.full(n * 3, 1.0 / N_YEARS / n))
    # Every draw of an event has the event's index; the losses differ.
    np.testing.assert_array_equal(es.index, np.repeat(base.index, n, axis=0))
    for d, factor in enumerate(StubDraws().factors):
        np.testing.assert_array_equal(es.loss[d::n], factor * base.loss)
    assert es.metadata.index == base.metadata.index
    names = [t.name for t in es.metadata.transforms]
    assert names == [BUILD_RECORD_NAME, "vulnerability_draws"]
    assert es.metadata.transforms[0].parameters["n_draws"] == n
    assert es.metadata.transforms[0].parameters["index"] == builder.parameters()


def test_builder_rejects_tracks_that_do_not_match_the_events(
    make_config: Callable[..., Any],
) -> None:
    from dataclasses import replace

    from climada.hazard import TCTracks

    captured: list[HazardBatch] = []

    @dataclass(frozen=True)
    class Capture:
        def describe(self, wind_field: str) -> Any:  # noqa: ANN401
            return CentroidWindIndex().describe(wind_field)

        def parameters(self) -> dict[str, Any]:
            return {"kind": "capture"}

        def build(self, batch: HazardBatch) -> NDArray[np.float64]:
            captured.append(batch)
            return batch.wind

    build_eventset(make_config(batch_size=3), index_builder=Capture())
    batch = captured[0]
    builder = CatInCircleIndex(radius_km=50)
    assert builder.build(batch).shape == (3, 3)
    reordered = replace(batch, tracks=TCTracks(list(reversed(batch.tracks.data))))
    with pytest.raises(ValueError, match="expected"):
        builder.build(reordered)
    with pytest.raises(ValueError, match="tracks for"):
        builder.build(replace(batch, tracks=TCTracks(batch.tracks.data[:1])))
    knots = batch.tracks.data[0].copy()
    knots.attrs["max_sustained_wind_unit"] = "m/s"
    wrong_unit = TCTracks([knots, *batch.tracks.data[1:]])
    with pytest.raises(ValueError, match="kn"):
        builder.build(replace(batch, tracks=wrong_unit))
