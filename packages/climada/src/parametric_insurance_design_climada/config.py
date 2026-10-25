"""Configuration of the track → wind → impact pipeline (MAR-73).

One YAML file configures one EventSet build (``pixi run build-eventset
--config <file>``). Every model forbids unknown keys. Relative paths in the
file are resolved against the file's directory, so a build does not depend
on the working directory. Example: ``packages/climada/configs/thesis.yaml``.

.. code-block:: yaml

    catalogue: ../../../data/iris/transformed/IRIS_NA_10000Y_merged.txt
    n_years: 10000
    locations:
      eventset: ../../../parity/tests/data/thesis_eventset  # or: yaml: assets.yaml
    proximity_km: 500
    batch_size: 500
    impact_function: {kind: emanuel_usa, impf_id: 1}
    output: ../../../data/eventsets/thesis-iris

The defaults reproduce the thesis ``engine.py``, except where
:class:`WindConfig` says otherwise.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from parametric_insurance_design.errors import ConfigError

__all__ = [
    "ImpactFunctionConfig",
    "LocationsConfig",
    "PipelineConfig",
    "PipelineConfigError",
    "WindConfig",
    "load_config",
    "parse_config",
]


class PipelineConfigError(ConfigError):
    """A pipeline configuration is invalid or cannot be read."""


class _Model(BaseModel):
    """Base of every config model: frozen, no unknown keys."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class LocationsConfig(_Model):
    """Where the asset locations come from. Give exactly one source.

    Attributes
    ----------
    eventset : pathlib.Path or None
        An EventSet directory; its ``locations`` table is used as it is
        (free columns included), e.g. the thesis parity fixture.
    yaml : pathlib.Path or None
        A YAML file with a top-level ``locations`` list of mappings with the
        keys ``location_id``, ``lat``, ``lon``, ``value``, ``name`` and any
        free columns.
    """

    eventset: Path | None = None
    yaml: Path | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> LocationsConfig:
        if (self.eventset is None) == (self.yaml is None):
            raise ValueError("give exactly one of 'eventset' and 'yaml'")
        return self

    @property
    def path(self) -> Path:
        """The configured source path."""
        path = self.eventset if self.eventset is not None else self.yaml
        assert path is not None  # guaranteed by the validator
        return path


class WindConfig(_Model):
    """Parameters of ``TropCyclone.from_tracks``.

    The defaults are CLIMADA's (6.1), as the thesis used them, with one
    exception: ``max_dist_inland_km`` defaults to None, which calls CLIMADA
    with ``ignore_distance_to_coast=True``. CLIMADA's default (1,000 km)
    makes CLIMADA download a 300 MB distance-to-coast raster on first use,
    outside this repository's checksummed downloads. For locations within
    1,000 km of the coast (the thesis portfolio) both give the same wind.

    Attributes
    ----------
    model : {"H08", "H1980", "H10", "ER11"}
        Parametric wind field model.
    intensity_thres : float
        Winds below this (m/s) are stored as 0.
    max_dist_eye_km : float
        No wind is computed farther than this from the storm's eye.
    max_latitude : float
        No wind is computed poleward of this latitude.
    max_dist_inland_km : float or None
        If set, no wind is computed farther inland than this (needs CLIMADA's
        distance-to-coast data). None ignores the distance to the coast.
    """

    model: Literal["H08", "H1980", "H10", "ER11"] = "H08"
    intensity_thres: float = Field(default=17.5, ge=0, allow_inf_nan=False)
    max_dist_eye_km: float = Field(default=300.0, gt=0, allow_inf_nan=False)
    max_latitude: float = Field(default=61.0, gt=0, le=90, allow_inf_nan=False)
    max_dist_inland_km: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class ImpactFunctionConfig(_Model):
    """The tropical-cyclone impact function applied to every location.

    Attributes
    ----------
    kind : {"emanuel_usa"}
        ``ImpfTropCyclone.from_emanuel_usa`` (Emanuel 2011), the thesis
        choice.
    impf_id : int
        CLIMADA impact function ID. If the locations have an ``impf_TC``
        column, every value must equal it.
    v_thresh, v_half : float
        Shape parameters in m/s (CLIMADA defaults 25.7 and 74.7).
    scale : float
        Linear scaling of the mean damage degree, in (0, 1].
    """

    kind: Literal["emanuel_usa"] = "emanuel_usa"
    impf_id: int = Field(default=1, ge=1, strict=True)
    v_thresh: float = Field(default=25.7, ge=0, allow_inf_nan=False)
    v_half: float = Field(default=74.7, gt=0, allow_inf_nan=False)
    scale: float = Field(default=1.0, gt=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def _half_above_threshold(self) -> ImpactFunctionConfig:
        if self.v_half <= self.v_thresh:
            raise ValueError("v_half must exceed v_thresh")
        return self


class PipelineConfig(_Model):
    """One EventSet build.

    Attributes
    ----------
    catalogue : pathlib.Path
        IRIS track catalogue (text), e.g. the merged 10,000-year file.
    n_years : int
        Simulated years the catalogue covers; every event gets the rate
        ``1 / n_years``. Catalogue years must lie in ``[0, n_years)``.
    locations : LocationsConfig
        Asset locations.
    proximity_km : float
        Storms whose track never passes within this distance of a location
        are left out (implicit zero-loss mass).
    batch_size : int
        Storms per CLIMADA call. Bounds memory; does not change the result.
    wind : WindConfig
        Wind field parameters.
    impact_function : ImpactFunctionConfig
        Impact function.
    hazard_release : str or None
        Release text for the EventSet's ``hazard.release``. If None, the
        catalogue must be the pinned IRIS merged file (checked by SHA256),
        and the release is taken from the IRIS manifest.
    scenario_id : str
        ``scenario_id`` of every event row.
    scenario : str or None
        Scenario description in the metadata. If None, one is generated.
    licence : str
        Licence of the data, written as the parity fixture does (the IRIS
        licence record is open under MAR-94).
    output : pathlib.Path
        EventSet directory to write.
    """

    catalogue: Path
    n_years: int = Field(gt=0, strict=True)
    locations: LocationsConfig
    proximity_km: float = Field(default=500.0, gt=0, allow_inf_nan=False)
    batch_size: int = Field(default=500, gt=0, strict=True)
    wind: WindConfig = WindConfig()
    impact_function: ImpactFunctionConfig = ImpactFunctionConfig()
    hazard_release: str | None = Field(default=None, min_length=1)
    scenario_id: str = Field(default="iris-present-climate", min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    licence: str = Field(default="CC0-1.0", min_length=1)
    output: Path


def _format_errors(exc: ValidationError, source: str | None) -> str:
    lines = []
    for item in exc.errors():
        loc = ".".join(str(part) for part in item["loc"]) or "<root>"
        lines.append(f"  {loc}: {item['msg']}")
    where = f" ({source})" if source else ""
    return f"invalid pipeline config{where}:\n" + "\n".join(lines)


def _resolve(base: Path, path: Path) -> Path:
    return path if path.is_absolute() else (base / path).resolve()


def parse_config(
    data: Mapping[str, Any],
    *,
    base_dir: str | Path | None = None,
    source: str | None = None,
) -> PipelineConfig:
    """Validate a config mapping.

    Parameters
    ----------
    data : mapping
        The config, e.g. parsed YAML.
    base_dir : str or pathlib.Path, optional
        Directory that relative paths are resolved against. If None, they
        stay as given.
    source : str, optional
        Name of the source, for error messages.

    Returns
    -------
    PipelineConfig
        The validated config.

    Raises
    ------
    PipelineConfigError
        If ``data`` is not a mapping or the config is invalid; the message
        lists every problem.
    """
    if not isinstance(data, Mapping):
        raise PipelineConfigError(
            f"invalid pipeline config ({source}): expected a mapping, "
            f"got {type(data).__name__}"
        )
    try:
        config = PipelineConfig.model_validate(data)
    except ValidationError as exc:
        raise PipelineConfigError(_format_errors(exc, source)) from exc
    if base_dir is None:
        return config
    base = Path(base_dir)
    locations = config.locations.model_copy(
        update={
            key: _resolve(base, value)
            for key in ("eventset", "yaml")
            if (value := getattr(config.locations, key)) is not None
        }
    )
    return config.model_copy(
        update={
            "catalogue": _resolve(base, config.catalogue),
            "output": _resolve(base, config.output),
            "locations": locations,
        }
    )


def load_config(path: str | Path) -> PipelineConfig:
    """Read a YAML pipeline config.

    Parameters
    ----------
    path : str or pathlib.Path
        The YAML file. Relative paths in it are resolved against its
        directory.

    Returns
    -------
    PipelineConfig
        The validated config, with absolute paths.

    Raises
    ------
    PipelineConfigError
        If the file cannot be read, is not YAML, or is invalid.
    """
    file = Path(path)
    try:
        data = yaml.safe_load(file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PipelineConfigError(f"cannot read config {file}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise PipelineConfigError(f"config {file} is not valid YAML: {exc}") from exc
    return parse_config(data, base_dir=file.resolve().parent, source=str(file))
