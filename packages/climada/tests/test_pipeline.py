"""End-to-end smoke tests of the track → wind → impact pipeline (MAR-73).

They run CLIMADA on the tiny synthetic catalogue of ``conftest.py`` (no
download) and check the EventSet against independent expectations.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml
from climada.entity.impact_funcs.trop_cyclone import ImpfTropCyclone
from climada.hazard import TropCyclone
from numpy.typing import NDArray

from parametric_insurance_design.eventset import (
    EventSet,
    IndexDefinition,
    TransformRecord,
)
from parametric_insurance_design_climada import iris
from parametric_insurance_design_climada.config import (
    LocationsConfig,
    PipelineConfigError,
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
    PipelineError,
    build_eventset,
    make_impact_function,
    read_locations,
)

from .conftest import LOCATIONS, N_YEARS

REPO = Path(__file__).resolve().parents[3]
FIXTURE = REPO / "parity" / "tests" / "data" / "thesis_eventset"
MODELLED = ["NA_10_1", "NA_3_0", "NA_8_0"]
WHEN = datetime(2026, 10, 25, tzinfo=UTC)


@pytest.fixture(scope="module")
def result(
    tmp_path_factory: pytest.TempPathFactory,
) -> Any:  # noqa: ANN401
    from parametric_insurance_design_climada.config import parse_config

    from .conftest import catalogue_text

    base = tmp_path_factory.mktemp("pipeline")
    (base / "iris.txt").write_text(catalogue_text(), encoding="utf-8")
    (base / "assets.yaml").write_text(
        yaml.safe_dump({"locations": LOCATIONS}), encoding="utf-8"
    )
    config = parse_config(
        {
            "catalogue": "iris.txt",
            "n_years": N_YEARS,
            "locations": {"yaml": "assets.yaml"},
            "batch_size": 2,
            "hazard_release": "synthetic test catalogue",
            "output": "out",
        },
        base_dir=base,
    )
    return build_eventset(config, created_at=WHEN)


def test_rows_are_the_modelled_storms_in_thesis_order(result: Any) -> None:  # noqa: ANN401
    es = result.eventset
    assert es.events["event_id"].tolist() == MODELLED
    assert es.events["year"].tolist() == [10, 3, 8]
    assert (es.events["draw_id"] == 0).all()
    assert (es.events["scenario_id"] == "iris-present-climate").all()
    np.testing.assert_array_equal(es.rates, np.full(3, 1.0 / N_YEARS))
    assert es.location_ids == ["L1", "L2", "L3"]
    assert es.locations["name"].tolist() == ["Brickell", "MiamiBeach", "Aventura"]


def test_storm_counts_and_skipped_storm_are_reported(result: Any) -> None:  # noqa: ANN401
    assert result.n_storms_catalogue == 5
    assert result.n_storms_near == 4
    assert [s.event_id for s in result.skipped] == ["NA_7_2"]
    assert "two" in result.skipped[0].reason
    record = result.eventset.metadata.transforms[0]
    assert record.parameters["skipped_storms"][0]["event_id"] == "NA_7_2"
    assert record.parameters["n_storms_within_radius"] == 4
    assert result.seconds > 0


def test_index_is_wind_and_strong_storm_hits_hardest(result: Any) -> None:  # noqa: ANN401
    index = result.eventset.index
    assert index.shape == (3, 3)
    hit = index[MODELLED.index("NA_3_0")]
    weak = index[MODELLED.index("NA_8_0")]
    assert (hit > 40).all()
    np.testing.assert_array_equal(weak, 0.0)
    assert (index[MODELLED.index("NA_10_1")] < hit).all()


def test_loss_is_value_times_emanuel_damage_of_the_wind(result: Any) -> None:  # noqa: ANN401
    es = result.eventset
    impf = ImpfTropCyclone.from_emanuel_usa()
    mdr = np.interp(es.index, impf.intensity, impf.mdd) * np.interp(
        es.index, impf.intensity, impf.paa
    )
    expected = mdr * es.locations["value"].to_numpy()[np.newaxis, :]
    np.testing.assert_allclose(es.loss, expected, rtol=1e-12, atol=0.0)
    assert es.loss[MODELLED.index("NA_3_0")].min() > 0


def test_metadata_records_climada_iris_and_impact_function(result: Any) -> None:  # noqa: ANN401
    from importlib.metadata import version

    meta = result.eventset.metadata
    assert meta.n_years == N_YEARS
    assert meta.hazard.name == "IRIS"
    assert meta.hazard.release == "synthetic test catalogue"
    assert meta.licence == "CC-BY-4.0"
    assert meta.loss.currency == "USD"
    assert meta.index.unit == "m/s"
    assert f"CLIMADA {version('climada')}" in meta.index.definition
    assert meta.provenance.producer == "parametric-insurance-design-climada"
    assert meta.provenance.created_at == WHEN
    assert set(meta.provenance.source_checksums) == {"iris.txt", "assets.yaml"}
    (record,) = meta.transforms
    assert record.name == BUILD_RECORD_NAME
    assert record.function.endswith("pipeline.build_eventset")
    params = record.parameters
    assert params["climada_version"] == version("climada")
    assert params["catalogue"]["n_storms"] == 5
    assert params["proximity_km"] == 500.0
    assert params["impact_function"]["v_thresh"] == 25.7
    assert params["impact_function"]["intensity"][-1] == 120.0
    assert params["index"] == {"kind": "centroid_wind"}
    assert params["n_draws"] == 1
    assert "batch_size" not in str(params)
    assert "storms" in meta.scenario
    assert "1 storm(s)" in meta.scenario


def test_parquet_round_trip_keeps_the_content_hash(
    result: Any,  # noqa: ANN401
    tmp_path: Path,
) -> None:
    es = result.eventset
    es.to_parquet(tmp_path / "es")
    back = EventSet.from_parquet(tmp_path / "es")
    assert back.equals(es)
    assert back.content_hash() == es.content_hash()


def test_batch_size_does_not_change_the_data(
    result: Any,  # noqa: ANN401
    make_config: Callable[..., Any],
) -> None:
    for batch_size in (1, 500):
        other = build_eventset(make_config(batch_size=batch_size), created_at=WHEN)
        np.testing.assert_array_equal(other.eventset.index, result.eventset.index)
        np.testing.assert_array_equal(other.eventset.loss, result.eventset.loss)


def test_same_inputs_give_the_same_content_hash(
    make_config: Callable[..., Any],
) -> None:
    first = build_eventset(make_config(batch_size=1)).eventset
    second = build_eventset(make_config(batch_size=3)).eventset
    assert first.content_hash() == second.content_hash()


def test_impact_function_change_changes_the_content_hash(
    make_config: Callable[..., Any],
) -> None:
    base = build_eventset(make_config()).eventset
    other = build_eventset(make_config(impact_function={"v_half": 80.0})).eventset
    assert base.content_hash() != other.content_hash()
    assert (other.loss <= base.loss).all()


def test_proximity_radius_drops_far_storms(make_config: Callable[..., Any]) -> None:
    result = build_eventset(make_config(proximity_km=200))
    assert result.eventset.events["event_id"].tolist() == ["NA_10_1", "NA_3_0"]
    assert [s.event_id for s in result.skipped] == ["NA_7_2"]


def test_unpinned_catalogue_needs_a_hazard_release(
    make_config: Callable[..., Any],
) -> None:
    with pytest.raises(PipelineConfigError, match="hazard_release"):
        build_eventset(make_config(hazard_release=None))


def test_pinned_catalogue_takes_release_from_the_manifest(
    make_config: Callable[..., Any],
    catalogue_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    real = iris.load_manifest()
    sha = iris.file_digests(catalogue_path)[1]
    fake = replace(real, merged=replace(real.merged, sha256=sha))
    monkeypatch.setattr(iris, "load_manifest", lambda: fake)
    es = build_eventset(make_config(hazard_release=None)).eventset
    assert real.collection_doi in es.metadata.hazard.release
    assert real.merged.name in es.metadata.hazard.release
    assert es.metadata.provenance.source_checksums[real.merged.name] == f"sha256:{sha}"


def test_catalogue_years_must_fit_n_years(make_config: Callable[..., Any]) -> None:
    with pytest.raises(PipelineError, match="n_years"):
        build_eventset(make_config(n_years=10))


def test_no_storm_near_the_locations_is_an_error(
    make_config: Callable[..., Any], tmp_path: Path
) -> None:
    far = tmp_path / "far.yaml"
    far.write_text(
        yaml.safe_dump(
            {
                "locations": [
                    {
                        "location_id": "X",
                        "lat": 60.0,
                        "lon": 10.0,
                        "value": 1.0,
                        "name": "Oslo",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(PipelineError, match="no storm"):
        build_eventset(make_config(locations={"yaml": str(far)}))


def test_locations_impf_column_must_match_the_impact_function(
    make_config: Callable[..., Any], tmp_path: Path
) -> None:
    path = tmp_path / "impf.yaml"
    rows = [{**row, "impf_TC": 2} for row in LOCATIONS]
    path.write_text(yaml.safe_dump({"locations": rows}), encoding="utf-8")
    with pytest.raises(PipelineConfigError, match="impf_TC"):
        build_eventset(make_config(locations={"yaml": str(path)}))
    result = build_eventset(
        make_config(locations={"yaml": str(path)}, impact_function={"impf_id": 2})
    )
    assert result.eventset.locations["impf_TC"].tolist() == [2, 2, 2]


# -- locations -------------------------------------------------------------


def test_read_locations_from_the_thesis_fixture() -> None:
    frame = read_locations(LocationsConfig(eventset=FIXTURE))
    assert frame["location_id"].tolist() == [f"A{k}" for k in range(1, 10)]
    assert "impf_TC" in frame.columns
    assert frame["value"].sum() == pytest.approx(156_500_000.0)


@pytest.mark.parametrize(
    ("content", "match"),
    [
        ({"assets": []}, "locations"),
        ({"locations": [{"location_id": "A", "lat": 1.0, "lon": 1.0}]}, "lack"),
        (
            {"locations": [dict(LOCATIONS[0]), dict(LOCATIONS[0])]},
            "repeat",
        ),
        ({"locations": [{**LOCATIONS[0], "lat": 95.0}]}, "range|lat"),
        ({"locations": [{**LOCATIONS[0], "value": float("nan")}]}, "finite"),
        ({"locations": [{**LOCATIONS[0], "lat": "north"}]}, "lat, lon and value"),
    ],
)
def test_read_locations_rejects_bad_tables(
    tmp_path: Path, content: dict[str, Any], match: str
) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(content), encoding="utf-8")
    with pytest.raises(PipelineConfigError, match=match):
        read_locations(LocationsConfig(yaml=path))


def test_read_locations_reports_unreadable_sources(tmp_path: Path) -> None:
    with pytest.raises(PipelineConfigError, match="cannot read"):
        read_locations(LocationsConfig(yaml=tmp_path / "missing.yaml"))
    with pytest.raises(PipelineConfigError, match="cannot read"):
        read_locations(LocationsConfig(eventset=tmp_path / "missing"))


# -- defaults match CLIMADA ------------------------------------------------


def test_wind_defaults_are_climadas() -> None:
    from parametric_insurance_design_climada.config import WindConfig

    params = inspect.signature(TropCyclone.from_tracks).parameters
    wind = WindConfig()
    assert wind.model == params["model"].default
    assert wind.intensity_thres == params["intensity_thres"].default
    assert wind.max_dist_eye_km == params["max_dist_eye_km"].default
    assert wind.max_latitude == params["max_latitude"].default


def test_impact_function_defaults_are_climadas(
    make_config: Callable[..., Any],
) -> None:
    params = inspect.signature(ImpfTropCyclone.from_emanuel_usa).parameters
    built = make_impact_function(make_config())
    reference = ImpfTropCyclone.from_emanuel_usa()
    np.testing.assert_array_equal(built.intensity, reference.intensity)
    np.testing.assert_array_equal(built.mdd, reference.mdd)
    assert params["v_thresh"].default == 25.7
    assert params["v_half"].default == 74.7


def test_inland_cut_off_is_passed_to_climada(make_config: Callable[..., Any]) -> None:
    from parametric_insurance_design_climada import pipeline

    off = make_config()
    on = make_config(wind={"max_dist_inland_km": 1000})
    assert pipeline._wind_kwargs(off)["ignore_distance_to_coast"] is True
    kwargs = pipeline._wind_kwargs(on)
    assert kwargs["ignore_distance_to_coast"] is False
    assert kwargs["max_dist_inland_km"] == 1000
    assert "max 1000 km inland" in pipeline._wind_field_text(on, "6.1.0")
    assert "no distance-to-coast" in pipeline._wind_field_text(off, "6.1.0")


# -- extension points ------------------------------------------------------


@dataclass(frozen=True)
class DoubledWind:
    """A toy index builder: twice the centroid wind."""

    def describe(self, wind_field: str) -> IndexDefinition:
        return IndexDefinition(definition=f"twice {wind_field}", unit="m/s")

    def parameters(self) -> dict[str, Any]:
        return {"kind": "doubled"}

    def build(self, batch: HazardBatch) -> NDArray[np.float64]:
        assert batch.n_events == len(batch.event_ids) == len(batch.tracks.data)
        assert batch.n_locations == 3
        return 2.0 * batch.wind


@dataclass(frozen=True)
class ScaledDraws:
    """A toy vulnerability hook: draws scale the base loss."""

    factors: tuple[float, ...] = (0.5, 1.5)

    @property
    def n_draws(self) -> int:
        return len(self.factors)

    def record(self, *, n_filters_before: int) -> TransformRecord | None:
        return TransformRecord(
            name="vulnerability_draws",
            function="tests.ScaledDraws",
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


def test_default_hooks_satisfy_the_protocols() -> None:
    assert isinstance(CentroidWindIndex(), IndexBuilder)
    assert isinstance(NoDraws(), VulnerabilityDraws)
    assert isinstance(DoubledWind(), IndexBuilder)
    assert isinstance(ScaledDraws(), VulnerabilityDraws)


def test_custom_index_builder_sets_index_and_definition(
    result: Any,  # noqa: ANN401
    make_config: Callable[..., Any],
) -> None:
    es = build_eventset(make_config(), index_builder=DoubledWind()).eventset
    np.testing.assert_array_equal(es.index, 2.0 * result.eventset.index)
    np.testing.assert_array_equal(es.loss, result.eventset.loss)
    assert es.metadata.index.definition.startswith("twice CLIMADA")
    assert es.metadata.transforms[0].parameters["index"] == {"kind": "doubled"}


def test_vulnerability_draws_expand_rows_event_major(
    result: Any,  # noqa: ANN401
    make_config: Callable[..., Any],
) -> None:
    base = result.eventset
    es = build_eventset(
        make_config(), vulnerability=ScaledDraws(), rng=np.random.default_rng(0)
    ).eventset
    assert es.n_rows == 2 * base.n_rows
    assert es.events["event_id"].tolist() == [e for e in MODELLED for _ in (0, 1)]
    assert es.events["draw_id"].tolist() == [0, 1] * 3
    np.testing.assert_allclose(es.rates, np.full(6, 1.0 / N_YEARS / 2))
    assert es.rates.sum() == pytest.approx(base.rates.sum())
    np.testing.assert_array_equal(es.index, np.repeat(base.index, 2, axis=0))
    np.testing.assert_array_equal(es.loss[0::2], 0.5 * base.loss)
    np.testing.assert_array_equal(es.loss[1::2], 1.5 * base.loss)
    names = [t.name for t in es.metadata.transforms]
    assert names == [BUILD_RECORD_NAME, "vulnerability_draws"]
    assert "2 vulnerability draws" in es.metadata.scenario


@dataclass(frozen=True)
class BadShape:
    def describe(self, wind_field: str) -> IndexDefinition:
        return IndexDefinition(definition="bad", unit="m/s")

    def parameters(self) -> dict[str, Any]:
        return {}

    def build(self, batch: HazardBatch) -> NDArray[np.float64]:
        return batch.wind[:, :1]


@dataclass(frozen=True)
class NegativeDraws(ScaledDraws):
    factors: tuple[float, ...] = (-1.0,)


@dataclass(frozen=True)
class ZeroDraws(ScaledDraws):
    factors: tuple[float, ...] = ()


def test_malformed_hook_output_is_an_error(make_config: Callable[..., Any]) -> None:
    rng = np.random.default_rng(0)
    with pytest.raises(PipelineError, match="shape"):
        build_eventset(make_config(), index_builder=BadShape())
    with pytest.raises(PipelineError, match="negative"):
        build_eventset(make_config(), vulnerability=NegativeDraws(), rng=rng)
    with pytest.raises(PipelineError, match="n_draws"):
        build_eventset(make_config(), vulnerability=ZeroDraws(), rng=rng)


def test_values_table_is_the_complete_dense_grid(result: Any) -> None:  # noqa: ANN401
    long = result.eventset.to_long()
    assert len(long) == 3 * 3
    assert isinstance(long, pd.DataFrame)
