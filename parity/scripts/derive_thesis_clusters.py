r"""Derive the thesis cluster assignments for the parity tests.

Runs the thesis clustering (``ClusterLevelIntegratedOptimizationApproach``
in ``src/implementation.ipynb`` of ``parametric-insurance-framework``) on the
9 Miami assets for ``n_clusters = 1 .. 9`` and writes the features and the
assignments to ``parity/golden/thesis_cluster_assignments.json``.

Two datasets, both built with the thesis' own functions
(``src/utils/data_processing.py``) from the thesis event-loss CSV:

``thesis_pipeline``
    The data the thesis clustered on: the notebook's data preparation
    (sub-portfolio, heteroscedastic noise layer with the configured level,
    draws and seed, probability ``1 / (N_YEARS * draws)``, rows kept where the
    maximum wind over the assets is ``>= ATTACHEMENT``). The thesis results
    (``Included_Assets`` in ``full_optimization_results.csv``) come from it.
``no_noise``
    The same without the noise layer (probability ``1 / N_YEARS``). It checks
    the clustering code alone, independent of the noise layer.

The thesis code is executed, not copied: the notebook cells holding the
imports, ``OptimizationConstructor`` and
``ClusterLevelIntegratedOptimizationApproach`` are found by their content and
run in a fresh namespace with the thesis configs. The thesis repository is
only read, never modified.

Run from the repository root::

    uv run python parity/scripts/derive_thesis_clusters.py \
        --thesis-repo ../parametric-insurance-framework --overwrite

The thesis repository may also be given with ``PARITY_THESIS_REPO``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import numpy as np
import pandas as pd
import scipy
import yaml  # thesis configs; PyYAML comes with the lint group (pre-commit)

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN = REPO_ROOT / "parity" / "golden" / "thesis_cluster_assignments.json"
N_CLUSTERS = tuple(range(1, 10))
DATASETS = ("thesis_pipeline", "no_noise")

_CELL_MARKERS = (
    "from scipy.cluster.hierarchy import",
    "class OptimizationConstructor",
    "class ClusterLevelIntegratedOptimizationApproach",
)


@dataclass(frozen=True)
class ThesisCode:
    """Handles on the executed thesis code and its configuration."""

    repo: Path
    commit: str
    data_processing: ModuleType
    cluster_approach: Any
    experiment_config: dict[str, Any]
    global_settings: dict[str, Any]

    @property
    def assets(self) -> list[str]:
        """The thesis asset ids, in config order."""
        return list(self.experiment_config["ASSETS"])

    @property
    def settings(self) -> dict[str, Any]:
        """The thesis settings the clustering depends on."""
        noise = self.experiment_config["NOISE_LAYER"]
        return {
            "beta_tail": float(self.global_settings["TAIL_QUANTILE_LEVEL"]),
            "linkage": "ward",
            "noise_value": float(noise["noise_value"]),
            "noise_type": str(noise["noise_type"]),
            "n_draws": int(noise["reshuffel"]),
            "random_seed": int(self.global_settings["RANDOM_SEED"]),
            "threshold": float(self.global_settings["ATTACHEMENT"]),
            "n_years": int(self.global_settings["N_YEARS"]),
        }


def load_thesis(repo: Path) -> ThesisCode:
    """Execute the thesis clustering code from a checkout.

    Parameters
    ----------
    repo : Path
        Root of a ``parametric-insurance-framework`` checkout.

    Returns
    -------
    ThesisCode
        The executed code and the thesis configs.
    """
    repo = repo.resolve()
    notebook = json.loads((repo / "src" / "implementation.ipynb").read_text("utf-8"))
    sources = ["".join(cell["source"]) for cell in notebook["cells"]]
    cells = []
    for marker in _CELL_MARKERS:
        found = [s for s in sources if marker in s]
        if len(found) != 1:
            raise RuntimeError(f"expected one notebook cell with {marker!r}")
        cells.append(found[0])
    configs = repo / "configs"
    experiment_config = yaml.safe_load((configs / "experiment_config.yaml").read_text())
    global_settings = yaml.safe_load((configs / "global_settings.yaml").read_text())
    namespace: dict[str, Any] = {
        "experiment_config": experiment_config,
        "global_settings": global_settings,
    }
    imports = "\n".join(
        line for line in cells[0].splitlines() if "__future__" not in line
    )
    exec("from __future__ import annotations\n" + imports, namespace)
    exec(cells[1], namespace)
    exec(cells[2], namespace)
    cls = namespace["ClusterLevelIntegratedOptimizationApproach"]
    # The clustering methods use no instance state, so skip __init__ (it
    # needs the payout attachment and limit only).
    approach = cls.__new__(cls)

    path = repo / "src" / "utils" / "data_processing.py"
    spec = importlib.util.spec_from_file_location("thesis_data_processing", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    data_processing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(data_processing)

    commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return ThesisCode(
        repo=repo,
        commit=commit,
        data_processing=data_processing,
        cluster_approach=approach,
        experiment_config=experiment_config,
        global_settings=global_settings,
    )


def thesis_frame(thesis: ThesisCode, dataset: str) -> pd.DataFrame:
    """Prepare the thesis simulation frame as the notebook does.

    Parameters
    ----------
    thesis : ThesisCode
        The executed thesis code.
    dataset : {"thesis_pipeline", "no_noise"}
        With or without the noise layer.

    Returns
    -------
    pandas.DataFrame
        The thesis ``transformed_simulation_df``.
    """
    if dataset not in DATASETS:
        raise ValueError(f"unknown dataset {dataset!r}")
    dp = thesis.data_processing
    s = thesis.settings
    assets = thesis.assets
    csv = thesis.repo / "data" / "output" / "climada_transformed_loss_data.csv"
    df = dp.create_sub_portfolio(pd.read_csv(csv), assets)
    n_draws = 1
    if dataset == "thesis_pipeline":
        n_draws = s["n_draws"]
        df = dp.add_noise_to_asset_losses(
            df=df,
            asset_data=assets,
            noise_level=s["noise_value"],
            noise_type=s["noise_type"],
            noise_reshuffel=n_draws,
            random_seed=s["random_seed"],
        )
    df = dp.calculate_portfolio_loss(df=df, asset_list=assets)
    df = dp.calculate_portfolio_max_wind(df=df, asset_list=assets)
    df = dp.calculate_annual_event_probabilities(
        df=df, years=s["n_years"], noise_reshuffel=n_draws
    )
    return dp.delete_events_below_threshold(
        df=df, threshold_column="Sub_Portfolio_Max_Wind", threshold_value=s["threshold"]
    )


def thesis_features(thesis: ThesisCode, frame: pd.DataFrame) -> pd.DataFrame:
    """Compute the thesis clustering features (not z-scored), one row per asset."""
    return thesis.cluster_approach._compute_features(
        simulation_df=frame,
        asset_ids=thesis.assets,
        asset_config=thesis.experiment_config["ASSETS"],
        beta_tail=thesis.settings["beta_tail"],
    )


def thesis_assignments(
    thesis: ThesisCode, frame: pd.DataFrame
) -> dict[int, dict[str, int]]:
    """Compute the thesis cluster labels for ``n_clusters = 1 .. 9``."""
    return {
        k: dict(
            thesis.cluster_approach._cluster_assets(
                simulation_df=frame,
                asset_ids=thesis.assets,
                asset_config=thesis.experiment_config["ASSETS"],
                n_clusters=k,
                beta_tail=thesis.settings["beta_tail"],
                linkage_method=thesis.settings["linkage"],
            )
        )
        for k in N_CLUSTERS
    }


def derive(thesis: ThesisCode) -> dict[str, Any]:
    """Build the golden document."""
    datasets: dict[str, Any] = {}
    for name in DATASETS:
        frame = thesis_frame(thesis, name)
        features = thesis_features(thesis, frame)
        datasets[name] = {
            "n_rows": len(frame),
            "features": {
                asset: {col: float(v) for col, v in row.items()}
                for asset, row in features.iterrows()
            },
            "assignments": {
                str(k): labels
                for k, labels in thesis_assignments(thesis, frame).items()
            },
        }
    return {
        "description": (
            "Thesis cluster assignments (scipy fcluster labels, cluster C<label>) "
            "and clustering features of the 9 Miami assets for n_clusters 1..9, "
            "from the thesis code. Written by "
            "parity/scripts/derive_thesis_clusters.py."
        ),
        "thesis_commit": thesis.commit,
        "versions": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "pandas": pd.__version__,
        },
        "settings": thesis.settings,
        "datasets": datasets,
    }


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=cast(str, __doc__).splitlines()[0])
    parser.add_argument(
        "--thesis-repo",
        type=Path,
        default=os.environ.get("PARITY_THESIS_REPO"),
        help="thesis checkout (default: $PARITY_THESIS_REPO)",
    )
    parser.add_argument("--output", type=Path, default=GOLDEN)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    if args.thesis_repo is None:
        parser.error("--thesis-repo or PARITY_THESIS_REPO is required")
    if args.output.exists() and not args.overwrite:
        parser.error(f"{args.output} exists; pass --overwrite")
    doc = derive(load_thesis(Path(args.thesis_repo)))
    args.output.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
