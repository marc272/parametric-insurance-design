r"""Migrate the thesis configuration to ``parity/configs/thesis.yaml`` (MAR-63).

The thesis (``parametric-insurance-framework``) configures its experiment in
four YAML files under ``configs/`` and in notebook globals:

- ``experiment_config.yaml``: assets, noise layer, baseline parameters;
- ``global_settings.yaml``: seed, attachment, limit, tail and KPI levels,
  number of years, paths, plot styling;
- ``optimization_config.yaml``: objectives and scopes, with the parameters each
  one takes;
- ``sweeps.yaml``: the one-factor-at-a-time sweep grids.

This script reads those four files (YAML only: the thesis code is never
imported, so no thesis dependency is needed) and writes one validated config
in the schema of :mod:`parametric_insurance_design.experiment.config`
(issue C2, C8). Every thesis key is accounted for: it maps to config fields
(:data:`FIELD_MAP`, :data:`STRUCTURE_MAP`), moved to the EventSet
(:data:`TO_EVENTSET`), or is dropped with a reason (:data:`DROPPED`). A key
outside these tables stops the migration (:class:`MigrationError`); nothing is
skipped silently. Settings the thesis fixed in code rather than in its YAML
files are listed in :data:`IMPLICIT`.

The thesis typos are read as written: ``ATTACHEMENT`` (``ATTACHMENT`` is
accepted too, as the thesis plotting code does) and ``reshuffel``.

Run from the repository root::

    uv run python parity/scripts/migrate_thesis_config.py \
        --thesis-repo ../parametric-insurance-framework --overwrite

``parity/tests/test_config_parity.py`` checks the committed file against the
thesis files field by field when ``PARITY_THESIS_REPO`` is set. The thesis
repository is only read, never modified.

This lives in ``parity/scripts`` rather than in the core library because it
encodes the thesis files' layout, names and typos: the library holds only the
schema.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Final, cast

import yaml

from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    dump_config,
    parse_config,
)

PARITY_DIR = Path(__file__).resolve().parents[1]
OUTPUT = PARITY_DIR / "configs" / "thesis.yaml"
EVENTSET_DIR = PARITY_DIR / "tests" / "data" / "thesis_eventset"

THESIS_REPO_ENV: Final = "PARITY_THESIS_REPO"
THESIS_CONFIG_DIR: Final = "configs"
THESIS_FILES: Final = (
    "experiment_config",
    "global_settings",
    "optimization_config",
    "sweeps",
)
"""The thesis config files, ``configs/<name>.yaml``."""

# Paths in thesis.yaml, relative to parity/configs/.
EVENTSET_PATH: Final = "../tests/data/thesis_eventset"
OUTPUT_DIRECTORY: Final = "../../results/thesis"

THESIS_RETURN_PERIODS: Final[tuple[float, ...]] = (
    2.0,
    5.0,
    10.0,
    20.0,
    50.0,
    100.0,
    200.0,
    500.0,
)
"""Return periods of the thesis exceedance curves (Figure 5.6): the default
of ``plot_exceedance_curves`` in the thesis ``src/utils/plotting.py``, which
the notebook does not override (MAR-117)."""

OBJECTIVE_KINDS: Final[Mapping[str, str]] = {
    "pure_basis_risk_minimization": "mse",
    "pure_uncovered_loss_minimization": "expected_uncovered",
    "weighted_cvar_minimization": "weighted_cvar",
}
"""Thesis objective (``Method``) to config ``objectives[].kind``."""

SCOPE_KINDS: Final[Mapping[str, str]] = {
    "individual_optimization": "individual",
    "cluster_optimization": "cluster",
    "integrated_portfolio_optimization": "portfolio",
}
"""Thesis scope (``Approach``) to config ``scopes[].kind``."""

OBJECTIVE_PARAMETERS: Final[Mapping[str, tuple[str, ...]]] = {
    "pure_basis_risk_minimization": ("budget_loading", "n_bins"),
    "pure_uncovered_loss_minimization": ("budget_loading", "n_bins"),
    "weighted_cvar_minimization": ("budget_loading", "n_bins", "alpha", "beta"),
}
"""Parameters each thesis objective takes (``OPTIMIZATION_OBJECTIVES``).

The config schema encodes the same applicability
(``ExperimentConfig.applies``); the migration stops if the thesis lists
differ.
"""

SCOPE_PARAMETERS: Final[Mapping[str, tuple[str, ...]]] = {
    "individual_optimization": (),
    "cluster_optimization": ("n_clusters",),
    "integrated_portfolio_optimization": (),
}
"""Parameters each thesis scope takes (``OPTIMIZATION_SCOPES``)."""

SWEEP_NAMES: Final[Mapping[str, str]] = {
    "alpha": "alpha",
    "beta": "beta",
    "budget_loading": "budget_loading",
    "n_clusters": "n_clusters",
    "n_bins": "n_bins",
    "n_assets": "n_assets",
    "noise_value": "noise_level",
}
"""Thesis ``VANILLA_SWEEPS`` name to config ``sweeps[].parameter``."""

FIELD_MAP: Final[tuple[tuple[str, str], ...]] = (
    ("experiment_config.NOISE_LAYER.noise_value", "noise.level"),
    ("experiment_config.NOISE_LAYER.noise_type", "noise.kind"),
    ("experiment_config.NOISE_LAYER.reshuffel", "noise.n_copies"),
    ("experiment_config.EXPERIMENT_INPUTS.alpha", "objectives[weighted_cvar].alpha"),
    ("experiment_config.EXPERIMENT_INPUTS.beta", "objectives[weighted_cvar].beta"),
    (
        "experiment_config.EXPERIMENT_INPUTS.budget_loading",
        "constraints[budget].loading",
    ),
    ("experiment_config.EXPERIMENT_INPUTS.n_clusters", "scopes[cluster].n_clusters"),
    ("experiment_config.EXPERIMENT_INPUTS.n_bins", "payout.n_bins"),
    ("global_settings.RANDOM_SEED", "noise.seed"),
    ("global_settings.RANDOM_SEED", "sweeps[n_assets].seed"),
    ("global_settings.ATTACHEMENT", "payout.attachment"),
    ("global_settings.ATTACHEMENT", "noise.bounds[0]"),
    ("global_settings.ATTACHEMENT", "threshold.value"),
    ("global_settings.LIMIT", "payout.limit"),
    ("global_settings.LIMIT", "noise.bounds[1]"),
    ("global_settings.TAIL_QUANTILE_LEVEL", "scopes[cluster].strategy.beta_tail"),
    ("global_settings.BENCHMARK_BETA", "evaluation.beta"),
    *(
        (f"sweeps.VANILLA_SWEEPS.{thesis}", f"sweeps[{name}].values")
        for thesis, name in SWEEP_NAMES.items()
    ),
)
"""Thesis scalar or list key to the config field that takes its value.

Config paths use ``[kind]`` (or ``[parameter]`` for sweeps) to pick the one
list entry of that kind, and ``[i]`` for a position (:func:`lookup`). A thesis
key may set several fields: the thesis used ``ATTACHEMENT`` as attachment,
noise ramp start and threshold, and ``RANDOM_SEED`` for the noise and the
asset-subset sampling. ``global_settings.ATTACHMENT`` is the corrected
spelling, read like ``ATTACHEMENT``.
"""

STRUCTURE_MAP: Final[tuple[tuple[str, str], ...]] = (
    ("experiment_config.ASSETS", "portfolio.location_ids (the asset keys, in order)"),
    (
        "optimization_config.OPTIMIZATION_OBJECTIVES",
        "objectives (one per key, kind from OBJECTIVE_KINDS)",
    ),
    (
        "optimization_config.OPTIMIZATION_SCOPES",
        "scopes (one per key, kind from SCOPE_KINDS)",
    ),
)
"""Thesis mappings whose keys become config lists. Their parameter lists must
equal :data:`OBJECTIVE_PARAMETERS` and :data:`SCOPE_PARAMETERS`."""

TO_EVENTSET: Final[tuple[tuple[str, str], ...]] = (
    ("experiment_config.ASSETS.*.name", "locations.name"),
    ("experiment_config.ASSETS.*.lat", "locations.lat"),
    ("experiment_config.ASSETS.*.lon", "locations.lon"),
    ("experiment_config.ASSETS.*.value", "locations.value"),
    ("experiment_config.ASSETS.*.impf_TC", "locations.impf_TC"),
    ("global_settings.N_YEARS", "metadata.n_years"),
    (
        "global_settings.DATA_PATH",
        "the EventSet itself (convert_thesis_eventset.py, MAR-9); config "
        "eventset.path and eventset.checksum",
    ),
)
"""Thesis keys that are data, not configuration: they live in the EventSet
fixture (``parity/tests/data/thesis_eventset``), converted by
``convert_thesis_eventset.py``. ``*`` is any asset id."""

DROPPED: Final[tuple[tuple[str, str], ...]] = (
    (
        "experiment_config.EXPERIMENT_INPUTS.risk_loading",
        "unused by the thesis code (SPEC §3.1 C8); loaded pricing is "
        "pricing.kind: cost_of_capital (MAR-27)",
    ),
    (
        "global_settings.OPTIMIZATION_RESULT_DIR",
        "replaced by output.directory: one result store for all tables (C4, C5)",
    ),
    (
        "global_settings.BENCHMARKING_RESULT_DIR",
        "replaced by output.directory: one result store for all tables (C4, C5)",
    ),
    (
        "global_settings.VISUALIZATION_DIR",
        "figures are the viz layer's output, which reads the result store (C6)",
    ),
    ("global_settings.COLOR_PALETTE", "plot styling, a viz concern (C6)"),
    (
        "global_settings.RESULT_DF_COLUMNS",
        "the wide result CSV is replaced by the records tables (C5)",
    ),
    (
        "sweeps.VANILLA_SWEEPS.transaction_costs",
        "no runs: the thesis applies these costs after the fact in "
        "plot_cluster_net_advantage, a figure (viz) input",
    ),
)
"""Thesis keys with no config field, and why. A path covers its subtree."""

IMPLICIT: Final[tuple[tuple[str, str], ...]] = (
    ("schema_version", "1"),
    ("name", "thesis"),
    ("eventset.path", f"{EVENTSET_PATH} (the MAR-9 fixture of DATA_PATH)"),
    ("eventset.checksum", "content_hash() of that fixture"),
    (
        "threshold.column",
        "index: delete_events_below_threshold on Sub_Portfolio_Max_Wind",
    ),
    ("basis", "event_conditional: probabilities rescaled after the filter (SPEC §6.2)"),
    ("sample", "full: calibration and KPIs on the same rows (in-sample)"),
    ("pricing", "pure: budget on the expected payout"),
    ("scopes[cluster].strategy", "thesis_ward, linkage ward (notebook clustering)"),
    (
        "sweeps[n_assets].max_combinations",
        "25: max_combos_per_n of the notebook's n_assets sensitivity cell",
    ),
    (
        "evaluation.return_periods",
        "2, 5, 10, 20, 50, 100, 200, 500: plot_exceedance_curves default "
        "(src/utils/plotting.py, Figure 5.6)",
    ),
    ("output.directory", f"{OUTPUT_DIRECTORY} (relative to parity/configs)"),
)
"""Config fields the thesis fixed in code, not in its YAML files."""


class MigrationError(ValueError):
    """The thesis files hold a key or value the migration does not know."""


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    """Return the SHA-256 of a file as ``sha256:<hex>``."""
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def thesis_paths(thesis_repo: Path) -> dict[str, Path]:
    """Return the path of each thesis config file in a thesis checkout."""
    return {
        name: thesis_repo / THESIS_CONFIG_DIR / f"{name}.yaml" for name in THESIS_FILES
    }


def read_thesis_configs(thesis_repo: Path) -> dict[str, dict[str, Any]]:
    """Read the four thesis config files.

    Parameters
    ----------
    thesis_repo : pathlib.Path
        Root of a thesis checkout.

    Returns
    -------
    dict
        File name (without ``.yaml``) to its parsed content.

    Raises
    ------
    MigrationError
        If a file is missing or does not hold a mapping.
    """
    out: dict[str, dict[str, Any]] = {}
    for name, path in thesis_paths(thesis_repo).items():
        if not path.is_file():
            raise MigrationError(f"thesis config {path} not found")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise MigrationError(f"thesis config {path} does not hold a mapping")
        out[name] = cast(dict[str, Any], data)
    return out


# --------------------------------------------------------------------------
# Inventory of thesis keys
# --------------------------------------------------------------------------


def leaf_paths(thesis: Mapping[str, Any]) -> Iterator[str]:
    """Yield the dotted path of every leaf of the thesis configs.

    Mappings are walked; anything else (scalars, lists) is a leaf. An empty
    mapping is a leaf too.
    """

    def walk(prefix: str, value: object) -> Iterator[str]:
        if isinstance(value, Mapping) and value:
            for key, child in value.items():
                yield from walk(f"{prefix}.{key}", child)
        else:
            yield prefix

    for name, content in thesis.items():
        yield from walk(name, content)


def _matches(pattern: str, path: str, *, subtree: bool) -> bool:
    """Whether ``path`` is ``pattern`` (or below it, with ``subtree``).

    ``*`` in the pattern matches one key.
    """
    regex = re.escape(pattern).replace(r"\*", r"[^.]+")
    tail = r"(\..+)?" if subtree else ""
    return re.fullmatch(regex + tail, path) is not None


def classify(path: str) -> str:
    """Return how a thesis leaf is migrated.

    Parameters
    ----------
    path : str
        Dotted leaf path, e.g. ``"global_settings.ATTACHEMENT"``.

    Returns
    -------
    str
        ``"field"`` (:data:`FIELD_MAP`), ``"eventset"`` (:data:`TO_EVENTSET`),
        ``"structure"`` (:data:`STRUCTURE_MAP`) or ``"dropped"``
        (:data:`DROPPED`).

    Raises
    ------
    MigrationError
        If the key is in none of the tables.
    """
    if path == "global_settings.ATTACHMENT" or any(p == path for p, _ in FIELD_MAP):
        return "field"
    if any(_matches(p, path, subtree=False) for p, _ in TO_EVENTSET):
        return "eventset"
    if any(_matches(f"{p}.*", path, subtree=False) for p, _ in STRUCTURE_MAP):
        return "structure"
    if any(_matches(p, path, subtree=True) for p, _ in DROPPED):
        return "dropped"
    raise MigrationError(
        f"thesis key {path!r} is not known to the migration; map it in "
        "FIELD_MAP, TO_EVENTSET or STRUCTURE_MAP, or drop it with a reason in DROPPED"
    )


# --------------------------------------------------------------------------
# Migration
# --------------------------------------------------------------------------


def _get(thesis: Mapping[str, Any], path: str) -> Any:  # noqa: ANN401 (YAML value)
    """Return the thesis value at a dotted path."""
    value: Any = thesis
    for key in path.split("."):
        if not isinstance(value, Mapping) or key not in value:
            raise MigrationError(f"thesis key {path!r} is missing")
        value = value[key]
    return value


def thesis_value(thesis: Mapping[str, Any], path: str) -> Any:  # noqa: ANN401
    """Return a thesis value, reading the attachment under either spelling.

    Parameters
    ----------
    thesis : mapping
        The four thesis configs (:func:`read_thesis_configs`).
    path : str
        Dotted path. ``global_settings.ATTACHEMENT`` (the thesis spelling)
        also reads ``global_settings.ATTACHMENT``.

    Raises
    ------
    MigrationError
        If the key is missing, or both spellings are set to different values.
    """
    if path != "global_settings.ATTACHEMENT":
        return _get(thesis, path)
    settings = thesis.get("global_settings", {})
    spellings = [k for k in ("ATTACHEMENT", "ATTACHMENT") if k in settings]
    if not spellings:
        raise MigrationError("global_settings has no ATTACHEMENT (or ATTACHMENT)")
    values = {settings[k] for k in spellings}
    if len(values) > 1:
        raise MigrationError(
            f"ATTACHEMENT and ATTACHMENT disagree: {sorted(values, key=repr)}"
        )
    return settings[spellings[0]]


def _check_parameter_lists(thesis: Mapping[str, Any]) -> None:
    """Check that the thesis objective and scope parameter lists are as expected."""
    for key, expected, kinds in (
        ("OPTIMIZATION_OBJECTIVES", OBJECTIVE_PARAMETERS, OBJECTIVE_KINDS),
        ("OPTIMIZATION_SCOPES", SCOPE_PARAMETERS, SCOPE_KINDS),
    ):
        given = _get(thesis, f"optimization_config.{key}")
        unknown = [name for name in given if name not in kinds]
        if unknown:
            raise MigrationError(f"{key} lists unknown entries {unknown}")
        for name, params in given.items():
            if tuple(params) != expected[name]:
                raise MigrationError(
                    f"{key}.{name} takes {list(params)}, the schema expects "
                    f"{list(expected[name])}"
                )


def migrate(
    thesis: Mapping[str, Any], *, eventset_checksum: str | None = None
) -> dict[str, Any]:
    """Return the config dict that replaces the thesis configs.

    Parameters
    ----------
    thesis : mapping
        The four thesis configs (:func:`read_thesis_configs`).
    eventset_checksum : str, optional
        ``content_hash()`` of the converted EventSet, for
        ``eventset.checksum``.

    Returns
    -------
    dict
        A config mapping in schema order; :func:`parse_config` accepts it.

    Raises
    ------
    MigrationError
        If a thesis file is missing, a key is unknown (:func:`classify`), or
        the parameter lists differ from the schema's.
    """
    missing = [name for name in THESIS_FILES if name not in thesis]
    if missing:
        raise MigrationError(f"thesis configs missing: {missing}")
    for path in leaf_paths(thesis):
        classify(path)
    _check_parameter_lists(thesis)

    def value(path: str) -> Any:  # noqa: ANN401
        return thesis_value(thesis, path)

    inputs = "experiment_config.EXPERIMENT_INPUTS"
    noise = "experiment_config.NOISE_LAYER"
    attachment, limit = (
        value("global_settings.ATTACHEMENT"),
        value("global_settings.LIMIT"),
    )
    seed = value("global_settings.RANDOM_SEED")

    scopes: list[dict[str, Any]] = []
    for name in value("optimization_config.OPTIMIZATION_SCOPES"):
        kind = SCOPE_KINDS[name]
        if kind == "cluster":
            scopes.append(
                {
                    "kind": "cluster",
                    "n_clusters": value(f"{inputs}.n_clusters"),
                    "strategy": {
                        "kind": "thesis_ward",
                        "beta_tail": value("global_settings.TAIL_QUANTILE_LEVEL"),
                        "linkage": "ward",
                    },
                }
            )
        else:
            scopes.append({"kind": kind})

    objectives: list[dict[str, Any]] = []
    for name in value("optimization_config.OPTIMIZATION_OBJECTIVES"):
        kind = OBJECTIVE_KINDS[name]
        if kind == "weighted_cvar":
            objectives.append(
                {
                    "kind": kind,
                    "alpha": value(f"{inputs}.alpha"),
                    "beta": value(f"{inputs}.beta"),
                }
            )
        else:
            objectives.append({"kind": kind})

    sweeps: list[dict[str, Any]] = []
    for name, values in value("sweeps.VANILLA_SWEEPS").items():
        if name not in SWEEP_NAMES:  # dropped (classify checked the rest)
            continue
        sweep: dict[str, Any] = {"parameter": SWEEP_NAMES[name], "values": list(values)}
        if name == "n_assets":
            sweep |= {"max_combinations": 25, "seed": seed}
        sweeps.append(sweep)

    return {
        "schema_version": 1,
        "name": "thesis",
        "description": (
            "The thesis experiment (parametric-insurance-framework, configs/*.yaml "
            "and notebook globals), migrated by parity/scripts/"
            "migrate_thesis_config.py for the parity runs (MAR-68)."
        ),
        "eventset": {"path": EVENTSET_PATH, "checksum": eventset_checksum},
        "portfolio": {"location_ids": list(value("experiment_config.ASSETS"))},
        "noise": {
            "kind": value(f"{noise}.noise_type"),
            "level": value(f"{noise}.noise_value"),
            "n_copies": value(f"{noise}.reshuffel"),
            "seed": seed,
            "bounds": [attachment, limit],
        },
        "threshold": {"value": attachment, "column": "index"},
        "basis": "event_conditional",
        "sample": {"kind": "full"},
        "payout": {
            "kind": "step",
            "attachment": attachment,
            "limit": limit,
            "n_bins": value(f"{inputs}.n_bins"),
        },
        "scopes": scopes,
        "objectives": objectives,
        "pricing": {"kind": "pure"},
        "constraints": [
            {"kind": "budget", "loading": value(f"{inputs}.budget_loading")}
        ],
        "evaluation": {
            "beta": value("global_settings.BENCHMARK_BETA"),
            "return_periods": list(THESIS_RETURN_PERIODS),
        },
        "sweeps": sweeps,
        "output": {"directory": OUTPUT_DIRECTORY},
    }


# --------------------------------------------------------------------------
# Lookup and rendering
# --------------------------------------------------------------------------


def lookup(data: Any, path: str) -> Any:  # noqa: ANN401 (config tree)
    """Return the value at a config path such as ``objectives[weighted_cvar].alpha``.

    ``[i]`` picks a list position; ``[name]`` picks the one list entry whose
    ``kind`` (or, for sweeps, ``parameter``) is ``name``.

    Raises
    ------
    KeyError
        If the path does not exist or ``[name]`` matches no or several entries.
    """
    value = data
    for part in re.findall(r"[^.\[\]]+|\[[^\]]+\]", path):
        if part.startswith("["):
            key = part[1:-1]
            if key.isdigit():
                value = value[int(key)]
                continue
            hits = [
                item
                for item in value
                if key in (item.get("kind"), item.get("parameter"))
            ]
            if len(hits) != 1:
                raise KeyError(f"{path}: {len(hits)} entries match [{key}]")
            value = hits[0]
        else:
            value = value[part]
    return value


def _comment(lines: Sequence[str]) -> str:
    return "".join(f"# {line}".rstrip() + "\n" for line in lines)


def render(config: ExperimentConfig, checksums: Mapping[str, str]) -> str:
    """Return ``thesis.yaml``: a provenance header, then the config as YAML.

    Parameters
    ----------
    config : ExperimentConfig
        The migrated config (relative paths, as written).
    checksums : mapping of str to str
        ``configs/<name>.yaml`` to its ``sha256:<hex>``, from the thesis
        checkout.
    """
    header = [
        "Thesis experiment configuration (MAR-63). GENERATED, do not edit:",
        "  uv run python parity/scripts/migrate_thesis_config.py \\",
        "      --thesis-repo ../parametric-insurance-framework --overwrite",
        "",
        "Source: parametric-insurance-framework, read-only:",
        *(f"  {name}  {digest}" for name, digest in checksums.items()),
        "",
        "Thesis key -> config field:",
        *(f"  {thesis} -> {field}" for thesis, field in FIELD_MAP),
        "  global_settings.ATTACHMENT is read as ATTACHEMENT (typo).",
        *(f"  {thesis} -> {field}" for thesis, field in STRUCTURE_MAP),
        "Thesis key -> EventSet (parity/tests/data/thesis_eventset):",
        *(f"  {thesis} -> {field}" for thesis, field in TO_EVENTSET),
        "Dropped thesis keys:",
        *(f"  {thesis}: {reason}" for thesis, reason in DROPPED),
        "Fixed in the thesis code, not in its YAML files:",
        *(f"  {field}: {source}" for field, source in IMPLICIT),
        "Relative paths are relative to this file's directory.",
    ]
    return _comment(header) + dump_config(config)


def build(thesis_repo: Path) -> str:
    """Migrate a thesis checkout and return the text of ``thesis.yaml``.

    Parameters
    ----------
    thesis_repo : pathlib.Path
        Root of a thesis checkout.

    Returns
    -------
    str
        The file content, deterministic for given inputs.
    """
    thesis = read_thesis_configs(thesis_repo)
    checksum = EventSet.from_parquet(EVENTSET_DIR).content_hash()
    config = parse_config(
        migrate(thesis, eventset_checksum=checksum), source="migration"
    )
    checksums = {
        f"{THESIS_CONFIG_DIR}/{path.name}": sha256_file(path)
        for path in thesis_paths(thesis_repo).values()
    }
    return render(config, checksums)


def main(argv: Sequence[str] | None = None) -> int:
    """Write :data:`OUTPUT` from a thesis checkout.

    Parameters
    ----------
    argv : sequence of str, optional
        Command-line arguments (default: ``sys.argv[1:]``).

    Returns
    -------
    int
        Exit code 0.
    """
    parser = argparse.ArgumentParser(description=cast(str, __doc__).splitlines()[0])
    parser.add_argument(
        "--thesis-repo",
        type=Path,
        default=os.environ.get(THESIS_REPO_ENV),
        help=f"thesis repository root (default: ${THESIS_REPO_ENV})",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    if args.thesis_repo is None:
        parser.error(f"pass --thesis-repo or set {THESIS_REPO_ENV}")
    if args.output.exists() and not args.overwrite:
        raise FileExistsError(f"{args.output} exists; pass --overwrite")
    text = build(Path(args.thesis_repo).expanduser().resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
