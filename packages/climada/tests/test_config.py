"""Tests for the pipeline config and its CLI (MAR-73)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from parametric_insurance_design.errors import ConfigError
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design_climada import cli
from parametric_insurance_design_climada.config import (
    PipelineConfigError,
    load_config,
    parse_config,
)

PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parents[1]


def test_thesis_config_resolves_against_its_directory() -> None:
    config = load_config(PACKAGE / "configs" / "thesis.yaml")
    assert config.catalogue == (
        REPO / "data" / "iris" / "transformed" / "IRIS_NA_10000Y_merged.txt"
    )
    assert config.locations.eventset == (
        REPO / "parity" / "tests" / "data" / "thesis_eventset"
    )
    assert config.locations.path.is_dir()
    assert config.output == REPO / "data" / "eventsets" / "thesis-iris"
    assert config.n_years == 10_000
    assert config.proximity_km == 500
    assert config.batch_size == 500
    assert config.wind.max_dist_inland_km is None
    assert config.impact_function.kind == "emanuel_usa"
    assert config.hazard_release is None
    assert config.licence == "CC0-1.0"


@pytest.mark.parametrize(
    ("update", "match"),
    [
        ({"proximty_km": 500}, "proximty_km"),
        ({"n_years": 0}, "n_years"),
        ({"n_years": 1.5}, "n_years"),
        ({"batch_size": 0}, "batch_size"),
        ({"locations": {}}, "exactly one"),
        ({"locations": {"yaml": "a.yaml", "eventset": "b"}}, "exactly one"),
        ({"impact_function": {"v_thresh": 80.0}}, "v_half"),
        ({"impact_function": {"scale": 1.5}}, "scale"),
        ({"impact_function": {"kind": "sigmoid"}}, "kind"),
        ({"wind": {"model": "X"}}, "model"),
        ({"wind": {"max_dist_inland_km": -1}}, "max_dist_inland_km"),
    ],
)
def test_invalid_configs_are_rejected(
    config_data: dict[str, Any], update: dict[str, Any], match: str
) -> None:
    with pytest.raises(PipelineConfigError, match=match):
        parse_config({**config_data, **update})


def test_config_error_is_a_core_config_error(config_data: dict[str, Any]) -> None:
    with pytest.raises(ConfigError):
        parse_config([])  # type: ignore[arg-type]


def test_load_config_reports_unreadable_files(tmp_path: Path) -> None:
    with pytest.raises(PipelineConfigError, match="cannot read"):
        load_config(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [", encoding="utf-8")
    with pytest.raises(PipelineConfigError, match="YAML"):
        load_config(bad)


def _write_config(tmp_path: Path, config_data: dict[str, Any]) -> Path:
    path = tmp_path / "pipeline.yaml"
    path.write_text(yaml.safe_dump(config_data), encoding="utf-8")
    return path


def test_cli_builds_and_writes_the_eventset(
    tmp_path: Path, config_data: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path, config_data)
    out = tmp_path / "es"
    assert cli.main(["--config", str(config), "--output", str(out), "--quiet"]) == 0
    printed = capsys.readouterr().out
    es = EventSet.from_parquet(out)
    assert es.n_rows == 3
    assert f"content_hash: {es.content_hash()}" in printed
    assert "skipped NA_7_2" in printed
    assert "3 rows x 3 locations" in printed

    # An existing EventSet is not replaced without --overwrite.
    assert cli.main(["--config", str(config), "--output", str(out), "--quiet"]) == 1
    assert "overwrite" in capsys.readouterr().err
    assert (
        cli.main(
            ["--config", str(config), "--output", str(out), "--overwrite", "--quiet"]
        )
        == 0
    )


def test_cli_catalogue_override_and_errors(
    tmp_path: Path, config_data: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(tmp_path, {**config_data, "catalogue": "missing.txt"})
    assert cli.main(["--config", str(config), "--quiet"]) == 1
    assert "error:" in capsys.readouterr().err
    code = cli.main(
        ["--config", str(config), "--catalogue", config_data["catalogue"], "--quiet"]
    )
    assert code == 0
    assert EventSet.from_parquet(config_data["output"]).n_rows == 3
    assert cli.main(["--config", str(tmp_path / "nope.yaml")]) == 1
