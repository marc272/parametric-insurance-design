"""Tests for the experiment config schema (MAR-63)."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml
from pydantic import ValidationError

from parametric_insurance_design.basis import Basis
from parametric_insurance_design.clustering import ThesisWardClustering
from parametric_insurance_design.constraints import Budget
from parametric_insurance_design.errors import ConfigError
from parametric_insurance_design.experiment import config as cfg
from parametric_insurance_design.experiment.config import (
    CONFIG_HASH_DOMAIN,
    SWEEP_PARAMETERS,
    ExperimentConfig,
    canonical_json,
    config_hash,
    dump_config,
    load_config,
    parse_config,
    to_dict,
)
from parametric_insurance_design.index import PointIndex, ValueWeightedIndex
from parametric_insurance_design.objectives import MSE, ExpectedUncovered, WeightedCVaR
from parametric_insurance_design.payout import StepPayout
from parametric_insurance_design.pricing import CostOfCapitalLoad, PurePremium
from parametric_insurance_design.scopes import Cluster, Individual, Portfolio

CHECKSUM = "sha256:" + "ab" * 32


def base() -> dict[str, Any]:
    """A complete, valid config in the thesis shape (small sweeps)."""
    return {
        "schema_version": 1,
        "name": "test",
        "description": "unit-test config",
        "eventset": {"path": "data/es", "checksum": CHECKSUM},
        "portfolio": {"location_ids": ["A", "B", "C"]},
        "noise": {
            "kind": "heteroscedastic",
            "level": 0.3,
            "n_copies": 13,
            "seed": 42,
            "bounds": [20, 70],
        },
        "threshold": {"value": 20, "column": "index"},
        "basis": "event_conditional",
        "sample": {"kind": "full"},
        "payout": {"kind": "step", "attachment": 20, "limit": 70, "n_bins": 15},
        "scopes": [
            {"kind": "individual"},
            {
                "kind": "cluster",
                "n_clusters": 2,
                "strategy": {"kind": "thesis_ward", "beta_tail": 0.9},
            },
            {"kind": "portfolio"},
        ],
        "objectives": [
            {"kind": "mse"},
            {"kind": "expected_uncovered"},
            {"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.95},
        ],
        "pricing": {"kind": "pure"},
        "constraints": [{"kind": "budget", "loading": 1}],
        "evaluation": {"beta": 0.95},
        "sweeps": [
            {"parameter": "alpha", "values": [0.1, 0.5, 1]},
            {"parameter": "beta", "values": [0.9, 0.99]},
            {"parameter": "budget_loading", "values": [0.5, 1.5]},
            {"parameter": "n_clusters", "values": [1, 2, 3]},
            {"parameter": "n_bins", "values": [5, 10]},
            {
                "parameter": "n_assets",
                "values": [1, 2],
                "max_combinations": 2,
                "seed": 7,
            },
            {"parameter": "noise_level", "values": [0, 0.5]},
        ],
        "output": {"directory": "results/test"},
    }


def minimal() -> dict[str, Any]:
    """The smallest valid config: required fields only."""
    return {
        "schema_version": 1,
        "name": "minimal",
        "eventset": {"path": "es"},
        "basis": "event",
        "payout": {"attachment": 0, "limit": 1, "n_bins": 2},
        "scopes": [{"kind": "portfolio"}],
        "objectives": [{"kind": "mse"}],
        "evaluation": {"beta": 0.9},
        "output": {"directory": "out"},
    }


def errors_of(data: object) -> str:
    with pytest.raises(ConfigError) as info:
        parse_config(data, source="test.yaml")  # type: ignore[arg-type]
    return str(info.value)


# --------------------------------------------------------------------------
# Valid configs and components
# --------------------------------------------------------------------------


def test_base_config_parses_with_coerced_floats() -> None:
    config = parse_config(base())
    assert config.payout.attachment == 20.0
    assert isinstance(config.payout.attachment, float)
    assert config.noise is not None
    assert config.noise.bounds == (20.0, 70.0)
    assert config.constraints[0].loading == 1.0
    assert isinstance(config.constraints[0].loading, float)
    assert config.portfolio.location_ids == ("A", "B", "C")
    assert config.basis is Basis.EVENT_CONDITIONAL
    noise_sweep = next(s for s in config.sweeps if s.parameter == "noise_level")
    assert noise_sweep.values == (0.0, 0.5)
    assert all(isinstance(v, float) for v in noise_sweep.values)


def test_minimal_config_defaults() -> None:
    config = parse_config(minimal())
    assert config.description == ""
    assert config.portfolio.location_ids is None
    assert config.noise is None
    assert config.threshold is None
    assert config.sample.kind == "full"
    assert config.pricing.kind == "pure"
    assert config.constraints == ()
    assert config.sweeps == ()
    assert config.eventset.checksum is None
    assert config.payout.kind == "step"


def test_to_components_builds_every_component() -> None:
    components = parse_config(base()).to_components()
    assert components.payout == StepPayout(attachment=20.0, limit=70.0, n_bins=15)
    individual, cluster, portfolio = components.scopes
    assert isinstance(individual, Individual)
    assert isinstance(individual.index, PointIndex)
    assert isinstance(cluster, Cluster)
    assert cluster.n_clusters == 2
    assert cluster.strategy == ThesisWardClustering(beta_tail=0.9, linkage="ward")
    assert isinstance(cluster.index, ValueWeightedIndex)
    assert portfolio == Portfolio()
    assert components.objectives == (
        MSE(),
        ExpectedUncovered(),
        WeightedCVaR(alpha=0.9, beta=0.95),
    )
    assert components.pricing == PurePremium()
    assert components.constraints == (Budget(loading=1.0),)
    assert components.basis is Basis.EVENT_CONDITIONAL


def test_kinds_are_the_component_names() -> None:
    # The config kinds are the components' record names (records.RUNS).
    components = parse_config(base()).to_components()
    config = parse_config(base())
    assert [s.kind for s in config.scopes] == [s.name for s in components.scopes]
    assert [o.kind for o in config.objectives] == [
        o.name for o in components.objectives
    ]
    assert config.pricing.kind == components.pricing.name
    assert config.payout.kind == components.payout.name
    assert [c.kind for c in config.constraints] == [
        c.name for c in components.constraints
    ]
    cluster = config.scopes[1]
    assert isinstance(cluster, cfg.ClusterScopeConfig)
    assert cluster.strategy.kind == ThesisWardClustering.name
    data = minimal()
    data["pricing"] = {"kind": "cost_of_capital", "rate": 0.08, "q": 0.99}
    pricing = parse_config(data).to_components().pricing
    assert pricing == CostOfCapitalLoad(rate=0.08, q=0.99)
    assert pricing.name == "cost_of_capital"


def test_index_override_and_explicit_breakpoints() -> None:
    data = minimal()
    data["scopes"] = [
        {"kind": "individual", "index": "value_weighted"},
        {"kind": "portfolio", "index": "value_weighted"},
        {
            "kind": "cluster",
            "n_clusters": 1,
            "strategy": {"kind": "thesis_ward", "beta_tail": 0.5, "linkage": "average"},
            "index": "point",
        },
    ]
    data["payout"] = {
        "attachment": 0,
        "limit": 10,
        "n_bins": 2,
        "breakpoints": [0, 3, 10],
    }
    components = parse_config(data).to_components()
    scopes = components.scopes
    assert all(isinstance(s, Individual | Portfolio | Cluster) for s in scopes)
    assert [type(getattr(s, "index")) for s in scopes] == [  # noqa: B009
        ValueWeightedIndex,
        ValueWeightedIndex,
        PointIndex,
    ]
    assert isinstance(components.payout, StepPayout)
    assert components.payout.edges.tolist() == [0.0, 3.0, 10.0]


@pytest.mark.parametrize(
    "sample",
    [
        {"kind": "holdout"},
        {"kind": "holdout", "train_fraction": 0.5},
        {"kind": "kfold"},
    ],
)
def test_sample_kinds(sample: dict[str, Any]) -> None:
    data = minimal()
    data["sample"] = sample
    config = parse_config(data)
    assert config.sample.kind == sample["kind"]


def test_noise_rng_is_fresh_and_seeded() -> None:
    config = parse_config(base())
    assert config.noise is not None
    first = config.noise.rng().normal(size=3)
    second = config.noise.rng().normal(size=3)
    np.testing.assert_array_equal(first, second)
    np.testing.assert_array_equal(first, np.random.default_rng(42).normal(size=3))


def test_models_are_frozen() -> None:
    config = parse_config(base())
    with pytest.raises(ValidationError):
        config.name = "other"  # type: ignore[misc]


def test_constructor_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        ExperimentConfig.model_validate({"schema_version": 1})


# --------------------------------------------------------------------------
# Invalid configs: readable errors
# --------------------------------------------------------------------------


def test_unknown_top_level_key_is_an_error_with_a_suggestion() -> None:
    data = base()
    data["objective"] = data.pop("objectives")
    message = errors_of(data)
    assert "invalid config (test.yaml)" in message
    assert "unknown key 'objective'" in message
    assert "did you mean 'objectives'?" in message


def test_thesis_typos_are_unknown_keys() -> None:
    data = base()
    data["noise"]["reshuffel"] = data["noise"].pop("n_copies")
    data["payout"]["ATTACHEMENT"] = 20
    message = errors_of(data)
    assert "noise: unknown key 'reshuffel'" in message
    assert "payout: unknown key 'ATTACHEMENT'" in message
    assert "allowed: kind, level, n_copies, seed, bounds" in message


def test_unknown_key_inside_a_list_entry() -> None:
    data = base()
    data["scopes"][1]["n_cluster"] = 3
    message = errors_of(data)
    assert "scopes[1].cluster: unknown key 'n_cluster'" in message
    assert "did you mean 'n_clusters'?" in message


def test_several_problems_are_listed_with_locations() -> None:
    data = base()
    data["payout"]["n_bins"] = 0
    data["objectives"][2]["alpha"] = 1.5
    data["evaluation"]["beta"] = "0.95"
    message = errors_of(data)
    assert "3 problems" in message
    assert (
        "payout.n_bins: Input should be greater than or equal to 1 (got 0)" in message
    )
    assert "objectives[2].weighted_cvar.alpha" in message
    assert "evaluation.beta: Input should be a valid number (got '0.95')" in message


@pytest.mark.parametrize(
    ("path", "value", "expected"),
    [
        (("payout", "n_bins"), True, "payout.n_bins: Input should be a valid integer"),
        (("payout", "n_bins"), 2.0, "payout.n_bins: Input should be a valid integer"),
        (("payout", "attachment"), float("nan"), "should be a finite number"),
        (("payout", "limit"), 10, "attachment must be < limit"),
        (("payout", "breakpoints"), [20, 30], "breakpoints must hold n_bins + 1"),
        (("noise", "bounds"), [70, 20], "bounds must satisfy low < high"),
        (
            ("noise", "level"),
            -0.1,
            "noise.level: Input should be greater than or equal",
        ),
        (("noise", "kind"), "lognormal", "noise.kind: Input should be"),
        (("noise", "seed"), -1, "noise.seed: Input should be greater than or equal"),
        (("threshold", "column"), "wind", "threshold.column"),
        (("eventset", "checksum"), "abc", "eventset.checksum: String should match"),
        (("portfolio", "location_ids"), [], "location_ids must not be empty"),
        (("portfolio", "location_ids"), ["A", "A"], "location_ids repeat ['A']"),
        (("schema_version",), 2, "schema_version 2 is not supported"),
        (("basis",), "yearly", "basis: Input should be"),
        (("scopes",), [], "scopes: must list at least one entry"),
        (("objectives",), [{"kind": "mse"}, {"kind": "mse"}], "repeated entries"),
        (
            ("constraints",),
            [{"kind": "budget", "loading": 1}, {"kind": "budget", "loading": 2}],
            "repeated entries: ['budget']",
        ),
        (("constraints",), [{"kind": "budget", "loading": -1}], "constraints[0]"),
        (("pricing",), {"kind": "loaded"}, "pricing: Input tag 'loaded'"),
        (("pricing",), {"kind": "cost_of_capital", "rate": 2, "q": 0.9}, "rate"),
        (("sample",), {"kind": "kfold", "k": 1}, "sample.kfold.k"),
        (("sample",), {"kind": "holdout", "train_fraction": 1}, "train_fraction"),
        (("name",), "", "name: String should have at least 1 character"),
    ],
)
def test_invalid_values_raise_readable_errors(
    path: tuple[str, ...], value: object, expected: str
) -> None:
    data = base()
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert expected in errors_of(data)


def test_invalid_clustering_linkage_fails_at_load_time() -> None:
    data = base()
    data["scopes"][1]["strategy"]["linkage"] = "nearest"
    assert "linkage must be one of" in errors_of(data)


def test_missing_required_fields_are_named() -> None:
    data = base()
    del data["evaluation"]
    del data["payout"]["n_bins"]
    message = errors_of(data)
    assert "evaluation: Field required" in message
    assert "payout.n_bins: Field required" in message


def test_non_mapping_is_rejected() -> None:
    assert "expected a mapping, got list" in errors_of([1, 2])
    with pytest.raises(ConfigError, match="expected a mapping, got NoneType"):
        parse_config(None)  # type: ignore[arg-type]


def test_long_inputs_are_shortened_in_messages() -> None:
    data = base()
    data["basis"] = "x" * 100
    assert "..." in errors_of(data)


# --------------------------------------------------------------------------
# Sweeps
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sweep", "expected"),
    [
        ({"parameter": "alpha", "values": []}, "has no values"),
        ({"parameter": "alpha", "values": [0.1, 0.1]}, "repeats values [0.1]"),
        ({"parameter": "n_bins", "values": [5.5]}, "n_bins values must be integers"),
        ({"parameter": "n_assets", "values": [0]}, "integers >= 1"),
        ({"parameter": "n_assets", "values": [4]}, "exceeds the 3 portfolio locations"),
        (
            {"parameter": "n_assets", "values": [1], "max_combinations": 3},
            "needs a seed",
        ),
        (
            {"parameter": "alpha", "values": [0.1], "seed": 1},
            "seed only apply to n_assets sweeps",
        ),
        ({"parameter": "alpha", "values": [1.5]}, "sweep 'alpha', value 1.5"),
        ({"parameter": "n_bins", "values": [0]}, "sweep 'n_bins', value 0"),
        ({"parameter": "eta", "values": [0.1]}, "sweeps[0].parameter"),
    ],
)
def test_invalid_sweeps(sweep: dict[str, Any], expected: str) -> None:
    data = base()
    data["sweeps"] = [sweep]
    assert expected in errors_of(data)


def test_repeated_sweep_parameter() -> None:
    data = base()
    data["sweeps"] = [
        {"parameter": "alpha", "values": [0.1]},
        {"parameter": "alpha", "values": [0.2]},
    ]
    assert "repeated entries: ['alpha']" in errors_of(data)


@pytest.mark.parametrize(
    ("parameter", "remove"),
    [
        ("alpha", ("objectives", 2)),
        ("beta", ("objectives", 2)),
        ("budget_loading", ("constraints", 0)),
        ("n_clusters", ("scopes", 1)),
    ],
)
def test_sweep_of_a_parameter_that_does_not_apply(
    parameter: str, remove: tuple[str, int]
) -> None:
    data = base()
    del data[remove[0]][remove[1]]
    data["sweeps"] = [{"parameter": parameter, "values": [1]}]
    assert f"sweep parameter {parameter!r} does not apply here" in errors_of(data)


def test_noise_and_n_bins_sweeps_need_their_component() -> None:
    data = base()
    data["noise"] = None
    data["sweeps"] = [{"parameter": "noise_level", "values": [0.1]}]
    assert "does not apply" in errors_of(data)
    data = base()
    data["payout"]["breakpoints"] = [20 + 50 * k / 15 for k in range(16)]
    data["sweeps"] = [{"parameter": "n_bins", "values": [5]}]
    assert "'n_bins' does not apply" in errors_of(data)


@pytest.mark.parametrize(
    ("parameter", "value", "get"),
    [
        ("alpha", 0.3, lambda c: c.objectives[2].alpha),
        ("beta", 0.99, lambda c: c.objectives[2].beta),
        ("budget_loading", 1.2, lambda c: c.constraints[0].loading),
        ("n_bins", 5, lambda c: c.payout.n_bins),
        ("n_clusters", 3, lambda c: c.scopes[1].n_clusters),
        ("noise_level", 0.7, lambda c: c.noise.level),
    ],
)
def test_with_parameter_sets_the_value_and_drops_sweeps(
    parameter: str, value: float, get: Callable[[ExperimentConfig], object]
) -> None:
    config = parse_config(base())
    point = config.with_parameter(parameter, value)
    assert get(point) == value
    assert point.sweeps == ()
    assert get(config) != value  # the original is unchanged
    assert config.applies(parameter)


def test_with_parameter_errors() -> None:
    config = parse_config(base())
    with pytest.raises(ConfigError, match="use with_locations"):
        config.with_parameter("n_assets", 2)
    with pytest.raises(ConfigError, match="unknown sweep parameter 'eta'"):
        config.with_parameter("eta", 0.1)
    with pytest.raises(ConfigError, match=r"objectives\[2\]\.weighted_cvar\.alpha"):
        config.with_parameter("alpha", 2.0)
    one = parse_config(minimal())
    with pytest.raises(ConfigError, match="'alpha' does not apply"):
        one.with_parameter("alpha", 0.5)
    assert one.applies("n_assets")
    assert set(SWEEP_PARAMETERS) == {
        "alpha",
        "beta",
        "budget_loading",
        "n_bins",
        "n_clusters",
        "noise_level",
        "n_assets",
    }


def test_with_locations() -> None:
    config = parse_config(base())
    point = config.with_locations(["C", "A"])
    assert point.portfolio.location_ids == ("C", "A")
    assert point.sweeps == ()
    with pytest.raises(ConfigError, match=r"not in the portfolio: \['D'\]"):
        config.with_locations(["A", "D"])
    with pytest.raises(ConfigError, match="location_ids repeat"):
        config.with_locations(["A", "A"])
    anywhere = parse_config(minimal()).with_locations(["X"])
    assert anywhere.portfolio.location_ids == ("X",)


def test_single_runs_are_scope_major_without_sweeps() -> None:
    config = parse_config(base())
    runs = config.single_runs()
    assert [(r.scopes[0].kind, r.objectives[0].kind) for r in runs] == [
        (s, o)
        for s in ("individual", "cluster", "portfolio")
        for o in ("mse", "expected_uncovered", "weighted_cvar")
    ]
    assert all(r.sweeps == () for r in runs)
    assert all(len(r.scopes) == len(r.objectives) == 1 for r in runs)
    assert len({config_hash(r) for r in runs}) == 9


# --------------------------------------------------------------------------
# Reading and writing
# --------------------------------------------------------------------------


def test_dump_and_parse_round_trip() -> None:
    config = parse_config(base())
    text = dump_config(config)
    again = parse_config(yaml.safe_load(text))
    assert again == config
    assert dump_config(again) == text
    assert "values: [0.1, 0.5, 1.0]" in text  # scalar lists on one line
    assert to_dict(config)["eventset"]["path"] == "data/es"


def test_load_config_resolves_relative_paths(tmp_path: Path) -> None:
    data = base()
    data["output"]["directory"] = str(tmp_path / "abs-out")
    file = tmp_path / "configs" / "exp.yaml"
    file.parent.mkdir()
    file.write_text(yaml.safe_dump(data), encoding="utf-8")
    config = load_config(file)
    assert config.eventset.path == (tmp_path / "configs" / "data" / "es").resolve()
    assert config.output.directory == tmp_path / "abs-out"
    # Paths are not hashed: the loaded config hashes like the parsed one.
    assert config_hash(config) == config_hash(parse_config(base()))


def test_load_config_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read config"):
        load_config(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [1, 2\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="is not valid YAML"):
        load_config(bad)
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text(yaml.safe_dump(minimal() | {"extra": 1}), encoding="utf-8")
    with pytest.raises(ConfigError, match=r"invalid\.yaml\), 1 problem:"):
        load_config(invalid)


# --------------------------------------------------------------------------
# Hashing
# --------------------------------------------------------------------------


def test_hash_format_and_pinned_value() -> None:
    # Pins the canonical form: any change to it must bump CONFIG_HASH_DOMAIN.
    # Independent check: printf "%s\\0%s" <domain> <json> | shasum -a 256.
    config = parse_config(minimal())
    digest = config_hash(config)
    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64
    assert CONFIG_HASH_DOMAIN == "parametric-insurance-design/config-hash/v1"
    assert canonical_json(config) == (
        '{"basis":"event","constraints":[],"evaluation":{"beta":0.9},'
        '"eventset":{"checksum":null},"noise":null,"objectives":[{"kind":"mse"}],'
        '"payout":{"attachment":0.0,"breakpoints":null,"kind":"step","limit":1.0,'
        '"n_bins":2},"portfolio":{"location_ids":null},"pricing":{"kind":"pure"},'
        '"sample":{"kind":"full"},"schema_version":1,'
        '"scopes":[{"index":null,"kind":"portfolio"}],"threshold":null}'
    )
    assert (
        digest
        == "sha256:8c0ec9b3beb9857188fd2e824b1e8edd03f2cc7538bb1eee84bceb1fad928937"
    )


def test_canonical_json_is_sorted_and_compact() -> None:
    text = canonical_json(parse_config(base()))
    assert " " not in text.replace("unit-test config", "")
    data = json.loads(text)
    assert list(data) == sorted(data)
    assert json.dumps(data, sort_keys=True, separators=(",", ":")) == text


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(name="other"),
        lambda d: d.update(description="other"),
        lambda d: d["eventset"].update(path="/elsewhere/es"),
        lambda d: d["output"].update(directory="/elsewhere/out"),
        lambda d: d.update(sweeps=[]),
        lambda d: d["constraints"][0].update(loading=1.0),  # 1 and 1.0
        lambda d: d["threshold"].update(value=20.0),
        lambda d: d["sample"].clear() or d["sample"].update(kind="full"),
        lambda d: d.update(dict(reversed(list(d.items())))),  # key order
    ],
    ids=[
        "name",
        "description",
        "eventset-path",
        "output",
        "sweeps",
        "int-vs-float",
        "threshold-float",
        "sample-default",
        "key-order",
    ],
)
def test_hash_ignores_labels_paths_sweeps_and_spelling(
    change: Callable[[dict[str, Any]], object],
) -> None:
    reference = config_hash(parse_config(base()))
    data = base()
    change(data)
    assert config_hash(parse_config(data)) == reference


def test_hash_equal_for_explicit_defaults_and_negative_zero() -> None:
    explicit = minimal() | {
        "portfolio": {"location_ids": None},
        "noise": None,
        "sample": {"kind": "full"},
        "pricing": {"kind": "pure"},
        "constraints": [],
        "sweeps": [],
        "description": "",
    }
    assert config_hash(parse_config(explicit)) == config_hash(parse_config(minimal()))
    zero = minimal() | {"threshold": {"value": 0.0}}
    negative = minimal() | {"threshold": {"value": -0.0}}
    assert canonical_json(parse_config(negative)) == canonical_json(parse_config(zero))


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["eventset"].update(checksum="sha256:" + "cd" * 32),
        lambda d: d["portfolio"].update(location_ids=["A", "B"]),
        lambda d: d["portfolio"].update(location_ids=["B", "A", "C"]),
        lambda d: d["noise"].update(seed=43),
        lambda d: d["noise"].update(bounds=[20, 71]),
        lambda d: d.update(threshold=None),
        lambda d: d.update(basis="annual"),
        lambda d: d.update(sample={"kind": "holdout"}),
        lambda d: d["payout"].update(n_bins=16),
        lambda d: d.update(scopes=list(reversed(d["scopes"]))),
        lambda d: d["objectives"][2].update(alpha=0.5),
        lambda d: d.update(pricing={"kind": "cost_of_capital", "rate": 0.1, "q": 0.99}),
        lambda d: d.update(constraints=[], sweeps=[]),
        lambda d: d["evaluation"].update(beta=0.99),
        lambda d: d["scopes"][0].update(index="value_weighted"),
    ],
    ids=[
        "checksum",
        "subset",
        "location-order",
        "seed",
        "bounds",
        "threshold",
        "basis",
        "sample",
        "n_bins",
        "scope-order",
        "alpha",
        "pricing",
        "constraints",
        "evaluation",
        "index",
    ],
)
def test_hash_changes_with_result_affecting_fields(
    change: Callable[[dict[str, Any]], object],
) -> None:
    reference = config_hash(parse_config(base()))
    data = copy.deepcopy(base())
    change(data)
    assert config_hash(parse_config(data)) != reference


def test_sweep_point_equal_to_baseline_shares_the_hash() -> None:
    config = parse_config(base())
    single = config.single_runs()[-1]  # portfolio x weighted_cvar
    assert config_hash(single.with_parameter("alpha", 0.9)) == config_hash(single)
    assert config_hash(single.with_parameter("alpha", 0.5)) != config_hash(single)
