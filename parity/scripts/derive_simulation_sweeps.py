r"""Regenerate the thesis simulation-sweep results from the thesis code (MAR-70).

The thesis computed its noise-level and number-of-assets sensitivity results
in memory only: ``benchmarking_kpis.csv`` has no ``noise_value_sweep`` or
``n_assets_sweep`` rows (MAR-67), and the asset-count figure shows averages
over asset subsets. This script runs the thesis' own sweep functions on the
thesis event-loss table and writes golden tables the parity harness reads.

What runs (the thesis repository is only read)
    The notebook cells that define the thesis optimisers and wrappers
    (``src/implementation.ipynb``: imports, ``optimization_scopes_baseline``,
    ``OptimizationConstructor``, the three scope classes,
    ``calibrate_payout_function``, ``append_optimization_results``,
    ``create_result_df``) are found by their content and executed in a fresh
    namespace with the thesis configs, as ``derive_thesis_clusters.py`` does.
    ``src/utils/sensitivity_analysis.py`` is then loaded with its own
    imports (``benchmarking``, ``data_processing``, ``formatting``,
    ``results``); its plotting imports (``src.utils.plotting``, matplotlib)
    are replaced by empty stand-ins, because only the figure rendering uses
    them. The script calls the thesis' ``_build_kpi_df_for_param`` exactly as
    the notebook's sensitivity cells do (``plot_sensitivity_analysis`` with
    ``param_name="noise_value"`` and ``"n_assets"``, ``asset="Portfolio"``,
    ``max_combos_per_n=25`` for ``n_assets``), with one difference: no
    ``exclude_combinations``, so every scope x objective runs (the cells
    excluded individual and cluster MSE and E[U] from the figures; that is a
    plotting choice, and our sweeps run them too, MAR-65).

What is recorded
    The thesis keeps per-subset results only inside ``_build_kpi_df_n_assets``
    and returns their averages. The script wraps three thesis functions it
    calls, without changing what they compute or return:

    * ``_build_sim_df``: notes the noise level and the asset subset of the
      data being built;
    * ``calibrate_payout_function``: records every exception before
      re-raising it (``_calibrate_objectives`` swallows it, so the thesis
      result simply lacks that scope x objective);
    * ``calculate_benchmarking_kpis``: keeps a copy of its input (the
      optimisation results: payouts) and its output (the KPI rows).

Outputs (``parity/golden/simulation_sweeps/``)
    ``results.csv.gz``
        The thesis payouts, as ``full_optimization_results.csv`` (payouts and
        breakpoints as numpy prints them), ``Source`` set to the sweep tag,
        plus ``Noise_Value`` (``noise_value_sweep`` only), ``N_Assets`` and
        ``Location_IDs`` (``n_assets_sweep`` only) and ``Subset_Index``.
    ``kpis.csv.gz``
        The thesis KPI rows, as ``benchmarking_kpis.csv``, with the same
        extra columns.
    ``objectives.csv``
        One golden objective per design problem, from the KPI rows above by
        the formulas of ``derive_golden_objectives.py`` (all at
        ``BENCHMARK_BETA`` = beta = 0.95): ``Derivation``
        ``a_thesis_rerun_kpis``.
    ``thesis_output.csv``
        What the thesis functions returned for the figures, Portfolio rows:
        per noise level the KPI row, per asset count the mean over subsets.
    ``provenance.json``
        Thesis commit and file checksums, versions, the subsets drawn and
        whether they equal ``sweeps.n_assets_subsets``, every recorded
        failure, row counts and output checksums, and the figure check below.

Figure check
    The notebook stores the figure data of both sensitivity cells (cell
    outputs: ``Param_Value``, ``KPI`` = ``CVaR_Uncovered`` of the portfolio,
    7 significant digits). The script compares the regenerated thesis output
    with it, records every value that differs by more than the print's
    rounding (:data:`PRINT_RTOL`), and fails if one differs by more than
    ``--figure-rtol`` (default 1e-4, the parity tolerance of SPEC F-06), so
    the golden tables are known to reproduce what the thesis showed. The
    regeneration runs with the workspace's solver versions, not the thesis'
    (``provenance.json`` records both).

Run from the repository root (about 25 minutes)::

    uv run python parity/scripts/derive_simulation_sweeps.py \
        --thesis-repo ../parametric-insurance-framework --overwrite
"""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Final, cast

import numpy as np
import pandas as pd
import yaml

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
OUT_DIR: Final[Path] = REPO_ROOT / "parity" / "golden" / "simulation_sweeps"
RESULTS: Final[str] = "results.csv.gz"
KPIS: Final[str] = "kpis.csv.gz"
OBJECTIVES: Final[str] = "objectives.csv"
THESIS_OUTPUT: Final[str] = "thesis_output.csv"
PROVENANCE: Final[str] = "provenance.json"

SWEEPS: Final[Mapping[str, str]] = {
    "noise_value": "noise_value_sweep",
    "n_assets": "n_assets_sweep",
}
"""Thesis sweep parameter to its ``Source`` tag."""

FIGURE_CELLS: Final[Mapping[str, str]] = {
    "noise_value": 'param_name="noise_value"',
    "n_assets": 'param_name="n_assets"',
}
"""Marker of each notebook sensitivity cell (``plot_sensitivity_analysis``)."""

MAX_COMBOS: Final[int] = 25
"""``max_combos_per_n`` of the notebook's ``n_assets`` cell."""

FIGURE_KPI: Final[str] = "CVaR_Uncovered"
"""The KPI the sensitivity figures plot (``kpi_col``)."""

PRINT_RTOL: Final[float] = 5e-7
"""Largest relative rounding of the figure print (7 significant digits)."""

_CELL_MARKERS: Final[tuple[str, ...]] = (
    "from scipy.cluster.hierarchy import",
    "optimization_scopes_baseline = {",
    "class OptimizationConstructor",
    "class IndividualOptimizationApproach",
    "class IntegratedPortfolioOptimizationApproach",
    "class ClusterLevelIntegratedOptimizationApproach",
    "def calibrate_payout_function",
)

_THESIS_FILES: Final[tuple[str, ...]] = (
    "src/implementation.ipynb",
    "src/utils/sensitivity_analysis.py",
    "src/utils/benchmarking.py",
    "src/utils/data_processing.py",
    "src/utils/formatting.py",
    "src/utils/results.py",
    "configs/experiment_config.yaml",
    "configs/global_settings.yaml",
    "configs/optimization_config.yaml",
    "configs/sweeps.yaml",
    "data/output/climada_transformed_loss_data.csv",
)

OBJECTIVE_FORMULAS: Final[Mapping[str, str]] = {
    "pure_basis_risk_minimization": "E_Residual^2",
    "pure_uncovered_loss_minimization": "E_Uncovered",
    "weighted_cvar_minimization": "Alpha * CVaR_Uncovered + (1 - Alpha) * E_Uncovered",
}


def sha256_file(path: Path) -> str:
    """Return the SHA256 hex digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def gz_content_sha256(path: Path) -> str:
    """Return the SHA256 of a gzipped file's decompressed content."""
    import gzip

    digest = hashlib.sha256()
    with gzip.open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------
# Loading the thesis code
# --------------------------------------------------------------------------


def _stub(name: str, **attrs: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module
    return module


def _load(name: str, path: Path) -> ModuleType:
    if not path.is_file():
        raise FileNotFoundError(f"thesis file missing: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - importlib quirk
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _unavailable(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("thesis plotting is not available in the parity script")


@dataclass
class Thesis:
    """The executed thesis code and its configuration."""

    repo: Path
    commit: str
    namespace: dict[str, Any]
    sensitivity: ModuleType
    notebook: dict[str, Any]
    experiment_config: dict[str, Any]
    global_settings: dict[str, Any]
    sweeps_config: dict[str, Any]

    @property
    def assets(self) -> list[str]:
        """The thesis asset ids, in config order."""
        return list(self.experiment_config["ASSETS"])


def load_thesis(repo: Path) -> Thesis:
    """Execute the thesis optimisers and load its sensitivity module.

    Parameters
    ----------
    repo : pathlib.Path
        Root of a ``parametric-insurance-framework`` checkout.

    Returns
    -------
    Thesis
        The namespace of the executed notebook cells and the loaded modules.

    Raises
    ------
    RuntimeError
        If a notebook cell marker is missing or ambiguous.
    """
    repo = repo.resolve()
    notebook = json.loads((repo / "src" / "implementation.ipynb").read_text("utf-8"))
    sources = [
        "".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code"
    ]
    cells = []
    for marker in _CELL_MARKERS:
        found = [s for s in sources if marker in s]
        if len(found) != 1:
            raise RuntimeError(f"expected one notebook cell with {marker!r}")
        cells.append(found[0])
    configs = repo / "configs"

    def config(name: str) -> dict[str, Any]:
        return cast(dict[str, Any], yaml.safe_load((configs / name).read_text("utf-8")))

    experiment_config = config("experiment_config.yaml")
    global_settings = config("global_settings.yaml")
    optimization_config = config("optimization_config.yaml")
    sweeps_config = config("sweeps.yaml")

    # The thesis package: real modules where the sweep code needs them,
    # empty stand-ins for the figure rendering (geopandas, matplotlib).
    for package in ("src", "src.utils"):
        stub = _stub(package)
        stub.__path__ = []
    utils = repo / "src" / "utils"
    _load("src.utils.formatting", utils / "formatting.py")
    _load("src.utils.data_processing", utils / "data_processing.py")
    _load("src.utils.benchmarking", utils / "benchmarking.py")
    _load("src.utils.results", utils / "results.py")
    _stub(
        "src.utils.plotting",
        _add_stacked_figure_legend=_unavailable,
        _add_figure_titles=_unavailable,
        plot_parameter_sweep=_unavailable,
    )
    if importlib.util.find_spec("matplotlib") is None:
        matplotlib = _stub("matplotlib")
        matplotlib.__path__ = []
        _stub("matplotlib.pyplot", subplots=_unavailable, rc_context=_unavailable)
        _stub("matplotlib.lines", Line2D=_unavailable)
    sensitivity = _load("src.utils.sensitivity_analysis", utils / "sensitivity_analysis.py")

    namespace: dict[str, Any] = {
        "experiment_config": experiment_config,
        "global_settings": global_settings,
        "optimization_config": optimization_config,
        "sweeps_config": sweeps_config,
    }
    imports = "\n".join(line for line in cells[0].splitlines() if "__future__" not in line)
    exec("from __future__ import annotations\n" + imports, namespace)  # noqa: S102
    for cell in cells[1:]:
        exec(cell, namespace)  # noqa: S102

    commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return Thesis(
        repo=repo,
        commit=commit,
        namespace=namespace,
        sensitivity=sensitivity,
        notebook=notebook,
        experiment_config=experiment_config,
        global_settings=global_settings,
        sweeps_config=sweeps_config,
    )


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------


@dataclass
class Evaluation:
    """One ``calculate_benchmarking_kpis`` call: a dataset and its results."""

    noise_value: float
    assets: tuple[str, ...]
    results: pd.DataFrame
    kpis: pd.DataFrame


@dataclass
class Failure:
    """One exception of ``calibrate_payout_function`` (swallowed by the thesis)."""

    noise_value: float
    assets: tuple[str, ...]
    approach: str
    method: str
    error_type: str
    message: str


@dataclass
class Recorder:
    """What the wrapped thesis functions saw (module docstring)."""

    noise_value: float = math.nan
    assets: tuple[str, ...] = ()
    evaluations: list[Evaluation] = field(default_factory=list)
    failures: list[Failure] = field(default_factory=list)


@contextmanager
def recording(thesis: Thesis, recorder: Recorder) -> Iterator[Callable[..., Any]]:
    """Wrap the thesis functions; yield the recording ``calibrate_payout_function``."""
    module = thesis.sensitivity
    build, kpis = module._build_sim_df, module.calculate_benchmarking_kpis
    calibrate = thesis.namespace["calibrate_payout_function"]

    def build_sim_df(**kwargs: Any) -> pd.DataFrame:
        recorder.noise_value = float(kwargs["noise_level"])
        recorder.assets = tuple(kwargs["asset_list"])
        return build(**kwargs)

    def calculate_benchmarking_kpis(**kwargs: Any) -> pd.DataFrame:
        out = kpis(**kwargs)
        recorder.evaluations.append(
            Evaluation(
                recorder.noise_value,
                recorder.assets,
                kwargs["optimization_results"].copy(),
                out.copy(),
            )
        )
        return out

    def calibrate_payout_function(**kwargs: Any) -> Any:
        try:
            return calibrate(**kwargs)
        except Exception as exc:
            recorder.failures.append(
                Failure(
                    recorder.noise_value,
                    recorder.assets,
                    str(kwargs["approach"]),
                    str(kwargs["method"]),
                    type(exc).__name__,
                    str(exc),
                )
            )
            raise

    module._build_sim_df = build_sim_df
    module.calculate_benchmarking_kpis = calculate_benchmarking_kpis
    try:
        yield calibrate_payout_function
    finally:
        module._build_sim_df = build
        module.calculate_benchmarking_kpis = kpis


def run_thesis_sweep(
    thesis: Thesis, parameter: str, raw: pd.DataFrame
) -> tuple[pd.DataFrame, Recorder, float]:
    """Run one thesis sensitivity sweep as the notebook cell does.

    Parameters
    ----------
    thesis : Thesis
        The executed thesis code.
    parameter : {"noise_value", "n_assets"}
        The sweep.
    raw : pandas.DataFrame
        The thesis event-loss table (``load_event_data``).

    Returns
    -------
    output : pandas.DataFrame
        What ``_build_kpi_df_for_param`` returned.
    recorder : Recorder
        The per-dataset results and the failures.
    seconds : float
        Wall time.
    """
    ns = thesis.namespace
    recorder = Recorder()
    start = time.perf_counter()
    with recording(thesis, recorder) as calibrate:
        output = thesis.sensitivity._build_kpi_df_for_param(
            param_name=parameter,
            sweep_values=thesis.sweeps_config["VANILLA_SWEEPS"][parameter],
            scopes=ns["optimization_scopes"],
            objectives=ns["optimization_objectives"],
            raw_df=raw,
            simulation_df=None,
            full_asset_list=thesis.assets,
            assets_config=thesis.experiment_config["ASSETS"],
            parameter_mapping=ns["optimization_scopes_baseline"],
            global_settings=thesis.global_settings,
            experiment_config=thesis.experiment_config,
            calibrate_payout_function=calibrate,
            run_sweep=ns.get("run_sweep"),
            append_optimization_results=ns["append_optimization_results"],
            create_result_df=ns["create_result_df"],
            asset="Portfolio",
            max_combos_per_n=MAX_COMBOS if parameter == "n_assets" else None,
            exclude_combinations=None,
        )
    return output, recorder, time.perf_counter() - start


# --------------------------------------------------------------------------
# Golden tables
# --------------------------------------------------------------------------


def _location_text(assets: Sequence[str]) -> str:
    return repr(list(assets))


def _subset_indices(evaluations: Sequence[Evaluation]) -> list[int]:
    """Position of each evaluation's subset among those of its size, in order."""
    seen: dict[int, int] = {}
    out = []
    for e in evaluations:
        n = len(e.assets)
        out.append(seen.get(n, 0))
        seen[n] = seen.get(n, 0) + 1
    return out


def _extras(parameter: str, e: Evaluation, index: int) -> dict[str, Any]:
    """The extra key columns of one evaluation's rows."""
    if parameter == "noise_value":
        return {
            "Noise_Value": e.noise_value,
            "N_Assets": math.nan,
            "Location_IDs": math.nan,
            "Subset_Index": math.nan,
        }
    return {
        "Noise_Value": math.nan,
        "N_Assets": len(e.assets),
        "Location_IDs": _location_text(e.assets),
        "Subset_Index": index,
    }


def _array_text(value: Any) -> Any:
    """A payout or breakpoint cell as the thesis CSV prints it (numpy ``str``)."""
    if isinstance(value, np.ndarray):
        return str(value)
    if isinstance(value, list | tuple):
        return str(np.asarray(value, dtype=float))
    return value


def golden_tables(
    parameter: str, recorder: Recorder
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return the results and KPI rows of one sweep, with the extra columns."""
    source = SWEEPS[parameter]
    results, kpis = [], []
    for e, index in zip(
        recorder.evaluations, _subset_indices(recorder.evaluations), strict=True
    ):
        extras = _extras(parameter, e, index)
        r = e.results.copy()
        r["Source"] = source
        for column in ("Payouts", "Breakpoints"):
            r[column] = [_array_text(v) for v in r[column]]
        r["Included_Assets"] = [
            v if isinstance(v, str) or v is None or v is pd.NA else repr(list(v))
            for v in r["Included_Assets"]
        ]
        k = e.kpis.copy()
        k["Source"] = source
        for name, value in extras.items():
            r[name] = value
            k[name] = value
        results.append(r)
        kpis.append(k)
    return (
        pd.concat(results, ignore_index=True),
        pd.concat(kpis, ignore_index=True),
    )


def objective_rows(kpis: pd.DataFrame, benchmark_beta: float) -> pd.DataFrame:
    """One golden objective per design problem, from the thesis KPI rows.

    Individual scope: one problem per asset (KPI subject the asset); cluster
    and portfolio scopes: the joint problem ``portfolio`` (subject
    ``Portfolio``). Weighted CVaR needs ``Beta`` = ``benchmark_beta``.
    """
    rows = []
    key = [
        "Approach",
        "Method",
        "Source",
        "Alpha",
        "Beta",
        "Budget_Loading",
        "N_Bins",
        "N_Clusters",
        "Noise_Value",
        "N_Assets",
        "Location_IDs",
        "Subset_Index",
    ]
    for record in kpis.to_dict("records"):
        individual = record["Approach"] == "individual_optimization"
        subject = str(record["Asset"])
        if individual == (subject == "Portfolio"):
            continue  # individual: asset rows; joint: the Portfolio row
        method = record["Method"]
        if method == "pure_basis_risk_minimization":
            value = float(record["E_Residual"]) ** 2
        elif method == "pure_uncovered_loss_minimization":
            value = float(record["E_Uncovered"])
        else:
            if not math.isclose(float(record["Beta"]), benchmark_beta):
                raise ValueError("weighted CVaR objective needs Beta = BENCHMARK_BETA")
            alpha = float(record["Alpha"])
            value = alpha * float(record["CVaR_Uncovered"]) + (1 - alpha) * float(
                record["E_Uncovered"]
            )
        rows.append(
            {
                **{k: record.get(k, math.nan) for k in key},
                "Problem": subject if individual else "portfolio",
                "Objective_Value": value,
                "Derivation": "a_thesis_rerun_kpis",
                "KPI_Source": f"thesis_rerun:{subject}",
            }
        )
    return pd.DataFrame(rows)


def thesis_output_rows(parameter: str, output: pd.DataFrame) -> pd.DataFrame:
    """The Portfolio rows the thesis returned for a figure, in a common shape."""
    column = "Noise_Value" if parameter == "noise_value" else "N_Assets"
    frame = output[output["Asset"] == "Portfolio"].copy()
    kpis = [
        "CVaR_Uncovered",
        "VaR_Uncovered",
        "E_Uncovered",
        "E_Residual",
        "E_Payout_to_E_Loss_Ratio",
        "Correlation",
    ]
    out = pd.DataFrame(
        {
            "Source": SWEEPS[parameter],
            "Approach": frame["Approach"].to_numpy(),
            "Method": frame["Method"].to_numpy(),
            "Param_Value": frame[column].astype(float).to_numpy(),
            **{k: frame[k].astype(float).to_numpy() for k in kpis},
        }
    )
    out["Aggregation"] = (
        "kpi_row" if parameter == "noise_value" else "mean_over_subsets"
    )
    return out


# --------------------------------------------------------------------------
# Figure check
# --------------------------------------------------------------------------


_ROW = re.compile(r"<tr>\s*<th>\d+</th>(.*?)</tr>", re.S)
_TD = re.compile(r"<td>(.*?)</td>", re.S)


def notebook_figure(thesis: Thesis, parameter: str) -> pd.DataFrame:
    """The figure data the notebook stored for a sensitivity cell.

    Parameters
    ----------
    thesis : Thesis
        The thesis checkout.
    parameter : {"noise_value", "n_assets"}
        The sweep.

    Returns
    -------
    pandas.DataFrame
        ``Param_Value``, ``KPI``, ``Scope``, ``Objective``, as the cell's
        HTML output shows them.

    Raises
    ------
    RuntimeError
        If the cell or its table output is not found.
    """
    marker = FIGURE_CELLS[parameter]
    cells = [
        c
        for c in thesis.notebook["cells"]
        if c["cell_type"] == "code"
        and "plot_sensitivity_analysis(" in "".join(c["source"])
        and marker in "".join(c["source"])
    ]
    if len(cells) != 1:
        raise RuntimeError(f"expected one sensitivity cell with {marker!r}")
    tables = [
        "".join(o["data"]["text/html"])
        for o in cells[0].get("outputs", [])
        if "data" in o and "text/html" in o["data"]
    ]
    if len(tables) != 1:
        raise RuntimeError(f"the {parameter} cell has no single table output")
    rows = []
    for row in _ROW.findall(tables[0]):
        cells_text = [html.unescape(t).strip() for t in _TD.findall(row)]
        if len(cells_text) != 4:
            raise RuntimeError(f"unexpected figure row {cells_text}")
        rows.append(
            {
                "Param_Value": float(cells_text[0]),
                "KPI": float(cells_text[1]),
                "Scope": cells_text[2],
                "Objective": cells_text[3],
            }
        )
    return pd.DataFrame(rows)


def figure_check(
    thesis: Thesis, parameter: str, output: pd.DataFrame, rtol: float
) -> dict[str, Any]:
    """Compare the regenerated thesis output with the notebook's figure data."""
    figure = notebook_figure(thesis, parameter)
    ours = thesis_output_rows(parameter, output)
    index = {
        (r["Approach"], r["Method"], float(r["Param_Value"])): float(r[FIGURE_KPI])
        for r in ours.to_dict("records")
    }
    worst = 0.0
    missing: list[list[Any]] = []
    beyond_print: list[dict[str, Any]] = []
    bad: list[dict[str, Any]] = []
    for r in figure.to_dict("records"):
        key = (r["Scope"], r["Objective"], float(r["Param_Value"]))
        if key not in index:
            missing.append(list(key))
            continue
        rel = abs(index[key] - r["KPI"]) / abs(r["KPI"]) if r["KPI"] else 0.0
        worst = max(worst, rel)
        item = {
            "key": list(key),
            "figure": r["KPI"],
            "regenerated": index[key],
            "rel_deviation": rel,
        }
        if rel > PRINT_RTOL:
            beyond_print.append(item)
        if rel > rtol:
            bad.append(item)
    combos = sorted({(r["Scope"], r["Objective"]) for r in figure.to_dict("records")})
    return {
        "kpi": FIGURE_KPI,
        "subject": "Portfolio",
        "figure_rows": len(figure),
        "figure_combinations": [list(c) for c in combos],
        "rtol": rtol,
        "print_rtol": PRINT_RTOL,
        "max_rel_deviation": worst,
        "missing": missing,
        "beyond_print_rounding": beyond_print,
        "outside_rtol": bad,
        "ok": not missing and not bad,
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def _versions() -> dict[str, str]:
    import cvxpy
    import scipy

    out = {
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.machine()}",
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "cvxpy": cvxpy.__version__,
    }
    for name in ("clarabel", "osqp", "scs"):
        try:
            from importlib.metadata import version

            out[name] = version(name)
        except Exception:  # noqa: BLE001 - optional solver, recorded as absent
            out[name] = "not installed"
    return out


def _subsets_check(thesis: Thesis, recorder: Recorder) -> dict[str, Any]:
    """Compare the thesis subsets with ``sweeps.n_assets_subsets``."""
    from parametric_insurance_design.experiment.sweeps import n_assets_subsets

    sizes = [int(v) for v in thesis.sweeps_config["VANILLA_SWEEPS"]["n_assets"]]
    ours = [
        list(s)
        for chosen in n_assets_subsets(
            thesis.assets,
            sizes,
            max_combinations=MAX_COMBOS,
            seed=int(thesis.global_settings["RANDOM_SEED"]),
        )
        for s in chosen
    ]
    theirs = [list(e.assets) for e in recorder.evaluations]
    return {
        "n_subsets": len(theirs),
        "per_size": {
            str(n): sum(len(s) == n for s in theirs) for n in sorted(set(sizes))
        },
        "equal_to_n_assets_subsets": theirs == ours,
        "subsets": [_location_text(s) for s in theirs],
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=cast(str, __doc__).splitlines()[0])
    parser.add_argument(
        "--thesis-repo",
        type=Path,
        default=os.environ.get("PARITY_THESIS_REPO"),
        help="thesis checkout (default: $PARITY_THESIS_REPO)",
    )
    parser.add_argument("--output", type=Path, default=OUT_DIR)
    parser.add_argument(
        "--sweep",
        action="append",
        choices=sorted(SWEEPS),
        help="thesis sweeps to run (default: both)",
    )
    parser.add_argument("--figure-rtol", type=float, default=1e-4)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    if args.thesis_repo is None:
        parser.error("--thesis-repo or PARITY_THESIS_REPO is required")
    out_dir: Path = args.output
    if (out_dir / PROVENANCE).exists() and not args.overwrite:
        parser.error(f"{out_dir} holds golden tables; pass --overwrite")
    parameters = tuple(args.sweep or SWEEPS)

    thesis = load_thesis(Path(args.thesis_repo))
    raw = pd.read_csv(thesis.repo / "data" / "output" / "climada_transformed_loss_data.csv")
    beta = float(thesis.global_settings["BENCHMARK_BETA"])

    results, kpis, outputs = [], [], []
    sweeps: dict[str, Any] = {}
    failed_check = False
    for parameter in parameters:
        print(f"running the thesis {parameter} sweep ...", flush=True)
        output, recorder, seconds = run_thesis_sweep(thesis, parameter, raw)
        r, k = golden_tables(parameter, recorder)
        results.append(r)
        kpis.append(k)
        outputs.append(thesis_output_rows(parameter, output))
        check = figure_check(thesis, parameter, output, args.figure_rtol)
        failed_check |= not check["ok"]
        entry: dict[str, Any] = {
            "source": SWEEPS[parameter],
            "values": thesis.sweeps_config["VANILLA_SWEEPS"][parameter],
            "seconds": round(seconds, 1),
            "datasets": len(recorder.evaluations),
            "result_rows": len(r),
            "kpi_rows": len(k),
            "failures": [
                {
                    "noise_value": f.noise_value,
                    "location_ids": list(f.assets),
                    "approach": f.approach,
                    "method": f.method,
                    "error_type": f.error_type,
                    "message": f.message,
                }
                for f in recorder.failures
            ],
            "figure_check": check,
        }
        if parameter == "n_assets":
            entry["subsets"] = _subsets_check(thesis, recorder)
            entry["max_combos_per_n"] = MAX_COMBOS
        sweeps[parameter] = entry
        print(
            f"  {len(recorder.evaluations)} datasets, {len(recorder.failures)} "
            f"failures, figure check {'ok' if check['ok'] else 'FAILED'} "
            f"(max rel. deviation {check['max_rel_deviation']:.2e}, "
            f"{len(check['beyond_print_rounding'])} beyond the print rounding), "
            f"{seconds:.0f} s",
            flush=True,
        )

    results_frame = pd.concat(results, ignore_index=True)
    kpis_frame = pd.concat(kpis, ignore_index=True)
    objectives_frame = objective_rows(kpis_frame, beta)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {
        RESULTS: results_frame,
        KPIS: kpis_frame,
        OBJECTIVES: objectives_frame,
        THESIS_OUTPUT: pd.concat(outputs, ignore_index=True),
    }
    for name, frame in files.items():
        # mtime=0 keeps the gzip bytes deterministic.
        compression = {"method": "gzip", "mtime": 0} if name.endswith(".gz") else None
        frame.to_csv(out_dir / name, index=False, compression=compression)
    outputs_meta = {}
    for name, frame in files.items():
        path = out_dir / name
        meta = {"rows": len(frame), "columns": len(frame.columns), "sha256": sha256_file(path)}
        if name.endswith(".gz"):
            meta["content_sha256"] = gz_content_sha256(path)
        outputs_meta[name] = meta
    provenance = {
        "description": (
            "Thesis simulation-sweep results (noise level, number of assets), "
            "regenerated by running the thesis code on its event-loss table "
            "(MAR-70). Written by parity/scripts/derive_simulation_sweeps.py; "
            "see its docstring."
        ),
        "thesis_commit": thesis.commit,
        "thesis_files": {
            name: sha256_file(thesis.repo / name) for name in _THESIS_FILES
        },
        "versions": _versions(),
        "settings": {
            "benchmark_beta": beta,
            "random_seed": int(thesis.global_settings["RANDOM_SEED"]),
            "noise_layer": thesis.experiment_config["NOISE_LAYER"],
            "experiment_inputs": thesis.experiment_config["EXPERIMENT_INPUTS"],
            "exclude_combinations": None,
            "asset": "Portfolio",
        },
        "objective_formulas": dict(OBJECTIVE_FORMULAS),
        "sweeps": sweeps,
        "outputs": outputs_meta,
    }
    (out_dir / PROVENANCE).write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {out_dir}")
    if failed_check:
        print("the regenerated thesis output differs from the notebook figure", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
