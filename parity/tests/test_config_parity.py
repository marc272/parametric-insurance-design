"""Parity of the migrated thesis configuration (MAR-63).

Acceptance: the thesis config round-trips, thesis YAMLs -> ``thesis.yaml`` ->
models, checked field by field.

Two groups:

- Against committed files only (CI-runnable): ``parity/configs/thesis.yaml``
  loads, holds the thesis values, agrees with the settings recorded by the
  earlier parity work (manifest, EventSet fixture, clustering golden file),
  and is exactly what the migration script renders from its own content. The
  migration logic (typos, inventory, refusals) runs on a synthetic thesis
  config.
- Against the thesis files: run when ``PARITY_THESIS_REPO`` points at a
  checkout of ``parametric-insurance-framework``, skipped otherwise. The script
  regenerates ``thesis.yaml`` byte for byte, and every thesis key is checked
  against its config field, its EventSet attribute, or its drop reason.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pytest
import yaml

from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import (
    ClusterScopeConfig,
    ExperimentConfig,
    config_hash,
    load_config,
    parse_config,
    to_dict,
)
from parametric_insurance_design.noise import add_noise
from parametric_insurance_design.scopes import Cluster

PARITY_DIR = Path(__file__).resolve().parents[1]
SCRIPT = PARITY_DIR / "scripts" / "migrate_thesis_config.py"
THESIS_YAML = PARITY_DIR / "configs" / "thesis.yaml"
MANIFEST = PARITY_DIR / "manifest.json"
CLUSTER_GOLDEN = PARITY_DIR / "golden" / "thesis_cluster_assignments.json"
THESIS_ASSETS = [f"A{k}" for k in range(1, 10)]


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migrate_thesis_config", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mt = _load_script()


@pytest.fixture(scope="module")
def config() -> ExperimentConfig:
    return load_config(THESIS_YAML)


@pytest.fixture(scope="module")
def fixture_eventset() -> EventSet:
    return EventSet.from_parquet(mt.EVENTSET_DIR)


def header_checksums(text: str) -> dict[str, str]:
    """The ``configs/<name>.yaml  sha256:...`` lines of the file header."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        parts = line.lstrip("# ").split()
        if len(parts) == 2 and parts[0].startswith("configs/"):
            out[parts[0]] = parts[1]
    return out


# --------------------------------------------------------------------------
# Committed files only
# --------------------------------------------------------------------------


def test_thesis_yaml_holds_the_thesis_values(config: ExperimentConfig) -> None:
    # Values from the thesis configs/*.yaml (see the header of thesis.yaml).
    assert config.name == "thesis"
    assert config.portfolio.location_ids == tuple(THESIS_ASSETS)
    assert config.noise is not None
    noise = config.noise
    assert (noise.kind, noise.level, noise.n_copies, noise.seed) == (
        "heteroscedastic",
        0.3,
        13,
        42,
    )
    assert noise.bounds == (20.0, 70.0)
    assert config.threshold is not None
    assert (config.threshold.value, config.threshold.column) == (20.0, "index")
    assert config.basis == "event_conditional"
    assert config.sample.kind == "full"
    payout = config.payout
    assert (payout.attachment, payout.limit, payout.n_bins) == (20.0, 70.0, 15)
    assert payout.breakpoints is None
    assert [s.kind for s in config.scopes] == ["individual", "cluster", "portfolio"]
    cluster = config.scopes[1]
    assert isinstance(cluster, ClusterScopeConfig)
    assert cluster.n_clusters == 3
    assert (cluster.strategy.beta_tail, cluster.strategy.linkage) == (0.9, "ward")
    assert [o.kind for o in config.objectives] == [
        "mse",
        "expected_uncovered",
        "weighted_cvar",
    ]
    assert to_dict(config)["objectives"][2] == {
        "kind": "weighted_cvar",
        "alpha": 0.9,
        "beta": 0.95,
    }
    assert config.pricing.kind == "pure"
    assert [(c.kind, c.loading) for c in config.constraints] == [("budget", 1.0)]
    assert config.evaluation.beta == 0.95
    # Thesis plot_exceedance_curves default (Figure 5.6), MAR-117.
    assert config.evaluation.return_periods == mt.THESIS_RETURN_PERIODS
    assert mt.THESIS_RETURN_PERIODS == (2, 5, 10, 20, 50, 100, 200, 500)
    sweeps = {s.parameter: s for s in config.sweeps}
    assert list(sweeps) == [
        "alpha",
        "beta",
        "budget_loading",
        "n_clusters",
        "n_bins",
        "n_assets",
        "noise_level",
    ]
    assert sweeps["alpha"].values == tuple(round(0.1 * k, 1) for k in range(1, 11))
    assert sweeps["beta"].values == tuple(round(0.9 + 0.01 * k, 2) for k in range(10))
    assert sweeps["budget_loading"].values == tuple(
        round(0.5 + 0.1 * k, 1) for k in range(11)
    )
    assert sweeps["n_clusters"].values == tuple(range(1, 10))
    assert sweeps["n_bins"].values == (5, 10, 15, 20, 25)
    assert sweeps["n_assets"].values == tuple(range(1, 10))
    assert (sweeps["n_assets"].max_combinations, sweeps["n_assets"].seed) == (25, 42)
    assert sweeps["noise_level"].values == tuple(round(0.1 * k, 1) for k in range(11))


def test_thesis_yaml_points_at_the_fixture(
    config: ExperimentConfig, fixture_eventset: EventSet
) -> None:
    assert config.eventset.path == mt.EVENTSET_DIR
    assert config.eventset.checksum == fixture_eventset.content_hash()
    assert fixture_eventset.location_ids == list(config.portfolio.location_ids or ())


def test_thesis_yaml_agrees_with_the_earlier_parity_records(
    config: ExperimentConfig,
) -> None:
    # MAR-9 recorded the checksums of two thesis config files, and MAR-12 the
    # settings its clustering golden file was derived with.
    checksums = header_checksums(THESIS_YAML.read_text(encoding="utf-8"))
    assert sorted(checksums) == [f"configs/{n}.yaml" for n in sorted(mt.THESIS_FILES)]
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for name in ("configs/experiment_config.yaml", "configs/global_settings.yaml"):
        assert checksums[name] == "sha256:" + manifest["sources"][name]["sha256"]
    settings = json.loads(CLUSTER_GOLDEN.read_text(encoding="utf-8"))["settings"]
    assert config.noise is not None
    assert config.threshold is not None
    cluster = config.scopes[1]
    assert isinstance(cluster, ClusterScopeConfig)
    assert {
        "beta_tail": cluster.strategy.beta_tail,
        "linkage": cluster.strategy.linkage,
        "noise_value": config.noise.level,
        "noise_type": config.noise.kind,
        "n_draws": config.noise.n_copies,
        "random_seed": config.noise.seed,
        "threshold": config.threshold.value,
    } == {k: v for k, v in settings.items() if k != "n_years"}


def test_thesis_yaml_is_the_rendered_migration(config: ExperimentConfig) -> None:
    # The committed file is generated, not hand-edited: rendering its own
    # content with its own header checksums gives the file back.
    text = THESIS_YAML.read_text(encoding="utf-8")
    as_written = parse_config(yaml.safe_load(text))
    assert as_written.eventset.path.as_posix() == mt.EVENTSET_PATH
    assert as_written.output.directory.as_posix() == mt.OUTPUT_DIRECTORY
    assert mt.render(as_written, header_checksums(text)) == text
    assert config_hash(as_written) == config_hash(config)


def test_thesis_config_builds_the_thesis_pipeline(
    config: ExperimentConfig, fixture_eventset: EventSet
) -> None:
    # The config carries everything the thesis data preparation and the
    # cluster scope need: it reproduces the MAR-12 golden cluster assignment.
    assert config.noise is not None
    assert config.threshold is not None
    noisy = add_noise(
        fixture_eventset,
        level=config.noise.level,
        kind=config.noise.kind,
        n_copies=config.noise.n_copies,
        rng=config.noise.rng(),
        bounds=config.noise.bounds,
        location_ids=config.portfolio.location_ids,
    )
    data = noisy.filter_threshold(
        config.threshold.value, column=config.threshold.column
    )
    golden = json.loads(CLUSTER_GOLDEN.read_text(encoding="utf-8"))
    expected = golden["datasets"]["thesis_pipeline"]
    assert data.n_rows == expected["n_rows"]
    cluster = config.to_components().scopes[1]
    assert isinstance(cluster, Cluster)
    (spec,) = cluster.partition(data)
    labels = {
        loc: int(entity.entity_id.removeprefix("C"))
        for entity in spec.entities
        for loc in entity.location_ids
    }
    assert labels == expected["assignments"][str(cluster.n_clusters)]


def test_thesis_sweep_points_are_valid(config: ExperimentConfig) -> None:
    runs = config.single_runs()
    assert len(runs) == 9
    for run in runs:
        for sweep in config.sweeps:
            if sweep.parameter == "n_assets" or not run.applies(sweep.parameter):
                continue
            for value in sweep.values:
                run.with_parameter(sweep.parameter, value)


# -- migration logic on a synthetic thesis config ---------------------------


def synthetic_thesis() -> dict[str, Any]:
    """A two-asset thesis config in the thesis layout, typos included."""
    return {
        "experiment_config": {
            "ASSETS": {
                "X1": {"name": "x1", "lat": 1.0, "lon": 2.0, "value": 3, "impf_TC": 1},
                "X2": {"name": "x2", "lat": 1.5, "lon": 2.5, "value": 4, "impf_TC": 1},
            },
            "NOISE_LAYER": {
                "noise_value": 0.2,
                "noise_type": "homoscedastic",
                "reshuffel": 3,
            },
            "EXPERIMENT_INPUTS": {
                "alpha": 0.5,
                "beta": 0.9,
                "budget_loading": 2,
                "risk_loading": 1,
                "n_clusters": 2,
                "n_bins": 4,
            },
        },
        "global_settings": {
            "RANDOM_SEED": 7,
            "ATTACHEMENT": 10,
            "LIMIT": 50,
            "TAIL_QUANTILE_LEVEL": 0.8,
            "BENCHMARK_BETA": 0.99,
            "N_YEARS": 100,
            "DATA_PATH": "x.csv",
            "OPTIMIZATION_RESULT_DIR": "o/",
            "BENCHMARKING_RESULT_DIR": "b/",
            "VISUALIZATION_DIR": "v/",
            "COLOR_PALETTE": {"Methods": {"a": "#000"}, "Font": {"family": "x"}},
            "RESULT_DF_COLUMNS": ["Approach"],
        },
        "optimization_config": {
            "OPTIMIZATION_OBJECTIVES": {
                "pure_basis_risk_minimization": ["budget_loading", "n_bins"],
                "weighted_cvar_minimization": [
                    "budget_loading",
                    "n_bins",
                    "alpha",
                    "beta",
                ],
            },
            "OPTIMIZATION_SCOPES": {
                "integrated_portfolio_optimization": [],
                "cluster_optimization": ["n_clusters"],
            },
        },
        "sweeps": {
            "VANILLA_SWEEPS": {
                "alpha": [0.1, 1],
                "n_assets": [1, 2],
                "noise_value": [0, 0.5],
                "transaction_costs": [1, 2],
            }
        },
    }


def test_migrate_maps_every_field() -> None:
    thesis = synthetic_thesis()
    data = mt.migrate(thesis)
    config = parse_config(data)
    tree = to_dict(config)
    for thesis_key, field in mt.FIELD_MAP:
        if thesis_key.startswith("sweeps.") and thesis_key.split(".")[-1] not in (
            "alpha",
            "n_assets",
            "noise_value",
        ):
            continue  # not in the synthetic sweeps
        assert mt.lookup(tree, field) == mt.thesis_value(thesis, thesis_key), field
    assert config.portfolio.location_ids == ("X1", "X2")
    assert [s.kind for s in config.scopes] == ["portfolio", "cluster"]
    assert [o.kind for o in config.objectives] == ["mse", "weighted_cvar"]
    assert [s.parameter for s in config.sweeps] == ["alpha", "n_assets", "noise_level"]
    assert config.eventset.checksum is None


def test_migrate_accepts_the_corrected_attachment_spelling() -> None:
    thesis = synthetic_thesis()
    settings = thesis["global_settings"]
    settings["ATTACHMENT"] = settings.pop("ATTACHEMENT")
    assert parse_config(mt.migrate(thesis)).payout.attachment == 10.0
    settings["ATTACHEMENT"] = 10
    assert parse_config(mt.migrate(thesis)).payout.attachment == 10.0
    settings["ATTACHEMENT"] = 11
    with pytest.raises(mt.MigrationError, match="ATTACHEMENT and ATTACHMENT disagree"):
        mt.migrate(thesis)
    del settings["ATTACHEMENT"], settings["ATTACHMENT"]
    with pytest.raises(mt.MigrationError, match="no ATTACHEMENT"):
        mt.migrate(thesis)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("global_settings", "NEW_SETTING"), 1, "'global_settings.NEW_SETTING' is not"),
        (("experiment_config", "ASSETS", "X1", "height"), 3, "ASSETS.X1.height"),
        (("experiment_config", "NOISE_LAYER", "reshuffle"), 3, "reshuffle"),
        (("sweeps", "VANILLA_SWEEPS", "gamma"), [1], "VANILLA_SWEEPS.gamma"),
        (
            ("optimization_config", "OPTIMIZATION_SCOPES", "global_optimization"),
            [],
            "unknown entries ['global_optimization']",
        ),
        (
            (
                "optimization_config",
                "OPTIMIZATION_OBJECTIVES",
                "weighted_cvar_minimization",
            ),
            ["n_bins"],
            "schema expects",
        ),
    ],
)
def test_migrate_refuses_unknown_keys(
    path: tuple[str, ...], value: object, message: str
) -> None:
    thesis = copy.deepcopy(synthetic_thesis())
    target: Any = thesis
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(mt.MigrationError, match=re.escape(message)):
        mt.migrate(thesis)


def test_migrate_refuses_missing_files_and_keys() -> None:
    thesis = synthetic_thesis()
    del thesis["sweeps"]
    with pytest.raises(
        mt.MigrationError, match=r"thesis configs missing: \['sweeps'\]"
    ):
        mt.migrate(thesis)
    thesis = synthetic_thesis()
    del thesis["global_settings"]["LIMIT"]
    with pytest.raises(mt.MigrationError, match=r"'global_settings\.LIMIT' is missing"):
        mt.migrate(thesis)


def test_lookup_rejects_ambiguous_selectors() -> None:
    tree = {"objectives": [{"kind": "mse"}, {"kind": "mse"}]}
    with pytest.raises(KeyError, match="2 entries match"):
        mt.lookup(tree, "objectives[mse]")
    assert mt.lookup({"a": [{"b": 1}]}, "a[0].b") == 1


# --------------------------------------------------------------------------
# Against the thesis files
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def thesis_repo() -> Path:
    value = os.environ.get(mt.THESIS_REPO_ENV)
    if not value:
        pytest.skip(
            f"{mt.THESIS_REPO_ENV} is not set; set it to a checkout of the "
            "thesis repository to migrate its configs/*.yaml"
        )
    repo = Path(value).expanduser()
    for path in mt.thesis_paths(repo).values():
        if not path.is_file():
            pytest.fail(f"{mt.THESIS_REPO_ENV}={value} does not hold {path}")
    return repo


@pytest.fixture(scope="module")
def thesis(thesis_repo: Path) -> dict[str, Any]:
    return mt.read_thesis_configs(thesis_repo)


def test_migration_regenerates_thesis_yaml(thesis_repo: Path) -> None:
    assert mt.build(thesis_repo) == THESIS_YAML.read_text(encoding="utf-8")


def test_header_checksums_are_the_thesis_files(thesis_repo: Path) -> None:
    checksums = header_checksums(THESIS_YAML.read_text(encoding="utf-8"))
    for path in mt.thesis_paths(thesis_repo).values():
        assert checksums[f"configs/{path.name}"] == mt.sha256_file(path)


def test_every_thesis_key_is_accounted_for(thesis: dict[str, Any]) -> None:
    kinds = {path: mt.classify(path) for path in mt.leaf_paths(thesis)}
    assert set(kinds.values()) == {"field", "eventset", "structure", "dropped"}
    # No stale table entries: each one covers a thesis key.
    for table in (mt.FIELD_MAP, mt.TO_EVENTSET, mt.STRUCTURE_MAP, mt.DROPPED):
        for pattern, _ in table:
            assert any(
                path == pattern or mt._matches(pattern, path, subtree=True)
                for path in kinds
            ), pattern


def test_thesis_fields_round_trip(
    thesis: dict[str, Any], config: ExperimentConfig
) -> None:
    # Field by field: thesis YAML value == value in the loaded thesis.yaml.
    tree = to_dict(config)
    for thesis_key, field in mt.FIELD_MAP:
        expected = mt.thesis_value(thesis, thesis_key)
        assert mt.lookup(tree, field) == expected, f"{thesis_key} -> {field}"


def test_thesis_structure_round_trips(
    thesis: dict[str, Any], config: ExperimentConfig
) -> None:
    assets = thesis["experiment_config"]["ASSETS"]
    assert config.portfolio.location_ids == tuple(assets)
    objectives = thesis["optimization_config"]["OPTIMIZATION_OBJECTIVES"]
    assert [o.kind for o in config.objectives] == [
        mt.OBJECTIVE_KINDS[n] for n in objectives
    ]
    assert {n: tuple(p) for n, p in objectives.items()} == mt.OBJECTIVE_PARAMETERS
    scopes = thesis["optimization_config"]["OPTIMIZATION_SCOPES"]
    assert [s.kind for s in config.scopes] == [mt.SCOPE_KINDS[n] for n in scopes]
    assert {n: tuple(p) for n, p in scopes.items()} == mt.SCOPE_PARAMETERS
    # The schema's sweep applicability covers every thesis parameter.
    for params in (*objectives.values(), *scopes.values()):
        for param in params:
            assert config.applies(param), param


def test_thesis_data_keys_are_in_the_eventset(
    thesis: dict[str, Any], thesis_repo: Path, fixture_eventset: EventSet
) -> None:
    locations = fixture_eventset.locations.set_index("location_id")
    for asset, attributes in thesis["experiment_config"]["ASSETS"].items():
        for key, value in attributes.items():
            got = locations.loc[asset, key]
            assert np.asarray(got).item() == value, (asset, key)
    settings = thesis["global_settings"]
    assert fixture_eventset.metadata.n_years == settings["N_YEARS"]
    # DATA_PATH is relative to the thesis src/ directory (the notebook's cwd).
    csv = (thesis_repo / "src" / settings["DATA_PATH"]).resolve()
    source = f"parametric-insurance-framework/{csv.relative_to(thesis_repo.resolve())}"
    checksums = fixture_eventset.metadata.provenance.source_checksums
    assert checksums[source] == mt.sha256_file(csv)
