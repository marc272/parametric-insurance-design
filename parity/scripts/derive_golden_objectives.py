r"""Build the golden objective table from the thesis outputs.

The thesis wrote no objective values: ``full_optimization_results.csv`` holds
payouts and ``benchmarking_kpis.csv`` KPIs. SPEC §7 F-06 asks for objective
parity, so this script derives one golden objective value per thesis design
problem and writes ``parity/golden/golden_objectives.csv`` (the harness'
objective table: the key columns, ``Problem``, ``Objective_Value``, plus
``Derivation`` and ``KPI_Source``) and ``parity/golden/golden_objectives.json``
(provenance: inputs and their SHA256, counts, and what is not compared).

Design problems (the store's ``runs.problem_id``)
    * individual scope: one problem per asset, ``Problem`` = the asset id;
      its objective is on that asset's loss and payout, so the KPI subject
      is the asset;
    * portfolio and cluster scopes: one joint problem, ``Problem`` =
      ``portfolio``; its objective is on the portfolio loss and the summed
      payout, so the KPI subject is ``Portfolio``.

Objectives in terms of the thesis KPIs (``benchmarking.py``, probabilities
rescaled to sum to one, CVaR in the Rockafellar-Uryasev sense)
    * ``pure_basis_risk_minimization``: ``E[(L - pi)^2]`` = ``E_Residual^2``;
    * ``pure_uncovered_loss_minimization``: ``E[U]`` = ``E_Uncovered``;
    * ``weighted_cvar_minimization``:
      ``Alpha * CVaR_Beta(U) + (1 - Alpha) * E[U]``.

How each golden value is obtained
    ``a_golden_kpis``
        From the committed golden KPI row of the problem's subject. For the
        weighted CVaR this needs the record's ``Beta`` to equal the KPI
        table's ``BENCHMARK_BETA`` (0.95).
    ``b_thesis_code``
        Recomputed with the thesis code where (a) does not apply: the
        thesis' own ``calculate_benchmarking_kpis`` (``benchmarking.py``), at
        ``benchmark_beta`` = the record's ``Beta``, applied to the golden
        payouts on the thesis-prepared data (the notebook's
        ``load_event_data``, ``create_sub_portfolio``,
        ``add_noise_to_asset_losses``, ``calculate_portfolio_loss``,
        ``calculate_portfolio_max_wind``,
        ``calculate_annual_event_probabilities`` and
        ``delete_events_below_threshold``, in that order). For a record the
        thesis dropped from its KPI table (some entity failed to solve), the
        problems that do have payouts are evaluated with the thesis'
        ``_build_standard_group_outputs`` and ``_calculate_entity_kpis``,
        which ``calculate_benchmarking_kpis`` calls itself.
    Not compared
        Everything else, listed in the JSON with a reason.

``KPI_Source`` names the KPI row used: ``golden:<subject>`` for (a);
``thesis_kpis:<subject>@beta=<b>`` (``calculate_benchmarking_kpis``) or
``thesis_entity_kpis:<subject>@beta=<b>`` (the entity helpers) for (b).

Before (b) is trusted, the script recomputes **every** KPI row of the golden
table with the same thesis pipeline at ``BENCHMARK_BETA`` and requires them
to equal the golden KPIs within ``--check-rtol`` and ``--check-atol``
(default 1e-5 relative plus 1e-6 absolute); it fails otherwise. They are not
bit-identical because the thesis computed its KPIs from the in-memory
payouts, and the CSV keeps 8 significant digits of them
(:func:`in_memory_rows`). The JSON records the largest deviation found.

Run from the repository root (the thesis repository is only read)::

    uv run python parity/scripts/derive_golden_objectives.py \
        --thesis-repo ../parametric-insurance-framework --overwrite

Without ``--thesis-repo`` only the (a) rows can be derived; the script then
refuses to write unless ``--a-only`` is given (tests use that mode).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import numpy as np
import pandas as pd
import yaml

PARITY_DIR: Final[Path] = Path(__file__).resolve().parents[1]
GOLDEN_DIR: Final[Path] = PARITY_DIR / "golden"
RESULTS: Final[Path] = GOLDEN_DIR / "full_optimization_results.csv.gz"
KPIS: Final[Path] = GOLDEN_DIR / "benchmarking_kpis.csv.gz"
OUT_CSV: Final[Path] = GOLDEN_DIR / "golden_objectives.csv"
OUT_JSON: Final[Path] = GOLDEN_DIR / "golden_objectives.json"

KEY_COLUMNS: Final[tuple[str, ...]] = (
    "Approach",
    "Method",
    "Source",
    "Alpha",
    "Beta",
    "Budget_Loading",
    "N_Bins",
    "N_Clusters",
)
OUT_COLUMNS: Final[tuple[str, ...]] = (
    *KEY_COLUMNS,
    "Problem",
    "Objective_Value",
    "Derivation",
    "KPI_Source",
)
KPI_VALUE_COLUMNS: Final[tuple[str, ...]] = (
    "CVaR_Uncovered",
    "VaR_Uncovered",
    "E_Uncovered",
    "E_Residual",
    "E_Payout_to_E_Loss_Ratio",
    "Correlation",
)

INDIVIDUAL: Final[str] = "individual_optimization"
JOINT_PROBLEM: Final[str] = "portfolio"
PORTFOLIO_SUBJECT: Final[str] = "Portfolio"
MSE: Final[str] = "pure_basis_risk_minimization"
EXPECTED_UNCOVERED: Final[str] = "pure_uncovered_loss_minimization"
WEIGHTED_CVAR: Final[str] = "weighted_cvar_minimization"

DERIVED_FROM_KPIS: Final[str] = "a_golden_kpis"
RECOMPUTED: Final[str] = "b_thesis_code"

FORMULAS: Final[Mapping[str, str]] = {
    MSE: "E_Residual^2",
    EXPECTED_UNCOVERED: "E_Uncovered",
    WEIGHTED_CVAR: "Alpha * CVaR_Uncovered + (1 - Alpha) * E_Uncovered",
}

# Thesis files read for (b), relative to the thesis repository root.
THESIS_DATA: Final[str] = "data/output/climada_transformed_loss_data.csv"
THESIS_EXPERIMENT: Final[str] = "configs/experiment_config.yaml"
THESIS_GLOBAL: Final[str] = "configs/global_settings.yaml"
THESIS_FORMATTING: Final[str] = "src/utils/formatting.py"
THESIS_PROCESSING: Final[str] = "src/utils/data_processing.py"
THESIS_BENCHMARKING: Final[str] = "src/utils/benchmarking.py"


class DerivationError(RuntimeError):
    """The golden objectives cannot be derived consistently."""


def sha256_file(path: str | Path) -> str:
    """Return the SHA256 hex digest of a file.

    Parameters
    ----------
    path : str or pathlib.Path
        The file.

    Returns
    -------
    str
        64 lowercase hex digits.
    """
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# Keys and formulas
# --------------------------------------------------------------------------


def _cell(value: object) -> float | None:
    """Return a golden parameter cell as a float, None if empty."""
    if value is None:
        return None
    number = float(value)  # type: ignore[arg-type]
    return None if math.isnan(number) else number


@dataclass(frozen=True)
class Record:
    """A golden record: approach, method, source and the five parameters."""

    approach: str
    method: str
    source: str
    alpha: float | None
    beta: float | None
    budget_loading: float | None
    n_bins: float | None
    n_clusters: float | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Record:
        """Build the record key of a golden row."""
        return cls(
            str(row["Approach"]).strip(),
            str(row["Method"]).strip(),
            str(row["Source"]).strip(),
            _cell(row["Alpha"]),
            _cell(row["Beta"]),
            _cell(row["Budget_Loading"]),
            _cell(row["N_Bins"]),
            _cell(row["N_Clusters"]),
        )

    def sort_key(self) -> tuple[object, ...]:
        """Return a total order (unset parameters first)."""
        params = (
            self.alpha,
            self.beta,
            self.budget_loading,
            self.n_bins,
            self.n_clusters,
        )
        return (
            self.source,
            self.approach,
            self.method,
            tuple((v is not None, v or 0.0) for v in params),
        )

    def columns(self) -> dict[str, object]:
        """Return the key columns of an output row (NaN for unset parameters)."""
        nan = math.nan
        return {
            "Approach": self.approach,
            "Method": self.method,
            "Source": self.source,
            "Alpha": nan if self.alpha is None else self.alpha,
            "Beta": nan if self.beta is None else self.beta,
            "Budget_Loading": nan
            if self.budget_loading is None
            else self.budget_loading,
            "N_Bins": nan if self.n_bins is None else self.n_bins,
            "N_Clusters": nan if self.n_clusters is None else self.n_clusters,
        }

    def label(self) -> str:
        """Readable key, e.g. ``beta_sweep/individual.../weighted.../beta=0.9``."""
        params = ", ".join(
            f"{name}={value:g}"
            for name, value in (
                ("alpha", self.alpha),
                ("beta", self.beta),
                ("budget_loading", self.budget_loading),
                ("n_bins", self.n_bins),
                ("n_clusters", self.n_clusters),
            )
            if value is not None
        )
        return f"{self.source}/{self.approach}/{self.method}/{params}"


def objective_from_kpis(
    method: str, alpha: float | None, kpis: Mapping[str, float]
) -> float:
    """Return the thesis objective value from the KPIs of its subject.

    Parameters
    ----------
    method : str
        Thesis ``Method``.
    alpha : float or None
        Thesis ``Alpha`` (weighted CVaR only).
    kpis : mapping of str to float
        ``E_Residual``, ``E_Uncovered`` and, for the weighted CVaR,
        ``CVaR_Uncovered`` at the record's ``Beta``.

    Returns
    -------
    float
        The objective value (formula in :data:`FORMULAS`).

    Raises
    ------
    DerivationError
        For an unknown method or a weighted CVaR without ``Alpha``.
    """
    if method == MSE:
        return float(kpis["E_Residual"]) ** 2
    if method == EXPECTED_UNCOVERED:
        return float(kpis["E_Uncovered"])
    if method == WEIGHTED_CVAR:
        if alpha is None:
            raise DerivationError("weighted CVaR record without Alpha")
        return alpha * float(kpis["CVaR_Uncovered"]) + (1.0 - alpha) * float(
            kpis["E_Uncovered"]
        )
    raise DerivationError(f"unknown Method {method!r}")


def problem_subject(approach: str, entity: str) -> tuple[str, str]:
    """Return (problem id, KPI subject) of a payout entity's design problem."""
    if approach == INDIVIDUAL:
        return entity, entity
    return JOINT_PROBLEM, PORTFOLIO_SUBJECT


def needs_thesis_code(record: Record, benchmark_beta: float) -> bool:
    """Whether the golden KPIs (at ``benchmark_beta``) cannot give the objective."""
    return record.method == WEIGHTED_CVAR and not (
        record.beta is not None
        and math.isclose(record.beta, benchmark_beta, rel_tol=1e-12, abs_tol=0.0)
    )


# --------------------------------------------------------------------------
# (a) from the golden KPIs
# --------------------------------------------------------------------------


def read_golden(
    results: Path = RESULTS, kpis: Path = KPIS
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read the golden results and KPI tables."""
    return pd.read_csv(results), pd.read_csv(kpis)


def _problems_by_record(results: pd.DataFrame) -> dict[Record, list[str]]:
    """Golden record to its design problems, from the payout rows."""
    out: dict[Record, list[str]] = {}
    for row in results.to_dict(orient="records"):
        record = Record.from_row(row)
        problem, _ = problem_subject(record.approach, str(row["Asset_ID"]).strip())
        problems = out.setdefault(record, [])
        if problem not in problems:
            problems.append(problem)
    return out


def _kpi_rows(kpis: pd.DataFrame) -> dict[tuple[Record, str], dict[str, float]]:
    out: dict[tuple[Record, str], dict[str, float]] = {}
    for row in kpis.to_dict(orient="records"):
        key = (Record.from_row(row), str(row["Asset"]).strip())
        if key in out:
            raise DerivationError(f"KPI table repeats {key[0].label()} / {key[1]}")
        out[key] = {c: float(row[c]) for c in KPI_VALUE_COLUMNS}
    return out


@dataclass(frozen=True)
class Plan:
    """What can be derived how.

    ``from_kpis`` and ``by_thesis_code`` map (record, problem) to the KPI
    subject; ``not_compared`` maps it to a reason.
    """

    from_kpis: dict[tuple[Record, str], str]
    by_thesis_code: dict[tuple[Record, str], str]
    not_compared: dict[tuple[Record, str], str]


def plan(results: pd.DataFrame, kpis: pd.DataFrame, benchmark_beta: float) -> Plan:
    """Decide for every golden design problem how its objective is obtained.

    Parameters
    ----------
    results, kpis : pandas.DataFrame
        The golden tables.
    benchmark_beta : float
        ``beta`` of the golden CVaR KPIs (thesis ``BENCHMARK_BETA``).

    Returns
    -------
    Plan
        Every design problem with golden payouts, in one of the three groups.
    """
    kpi_rows = _kpi_rows(kpis)
    from_kpis: dict[tuple[Record, str], str] = {}
    by_code: dict[tuple[Record, str], str] = {}
    not_compared: dict[tuple[Record, str], str] = {}
    for record, problems in _problems_by_record(results).items():
        for problem in problems:
            subject = PORTFOLIO_SUBJECT if problem == JOINT_PROBLEM else problem
            has_kpis = (record, subject) in kpi_rows
            if has_kpis and not needs_thesis_code(record, benchmark_beta):
                from_kpis[(record, problem)] = subject
            elif record.method in FORMULAS:
                by_code[(record, problem)] = subject
            else:  # pragma: no cover - every thesis method has a formula
                not_compared[(record, problem)] = f"no formula for {record.method}"
    return Plan(from_kpis, by_code, not_compared)


def derive_from_kpis(
    kpis: pd.DataFrame, items: Mapping[tuple[Record, str], str]
) -> list[dict[str, object]]:
    """Rows of the (a) objectives.

    Parameters
    ----------
    kpis : pandas.DataFrame
        The golden KPI table.
    items : mapping
        (record, problem) to KPI subject, from :func:`plan`.

    Returns
    -------
    list of dict
        Output rows (:data:`OUT_COLUMNS`).
    """
    kpi_rows = _kpi_rows(kpis)
    rows = []
    for (record, problem), subject in items.items():
        values = kpi_rows[(record, subject)]
        rows.append(
            {
                **record.columns(),
                "Problem": problem,
                "Objective_Value": objective_from_kpis(
                    record.method, record.alpha, values
                ),
                "Derivation": DERIVED_FROM_KPIS,
                "KPI_Source": f"golden:{subject}",
            }
        )
    return rows


# --------------------------------------------------------------------------
# (b) with the thesis code
# --------------------------------------------------------------------------


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


@dataclass(frozen=True)
class Thesis:
    """The thesis modules, settings and prepared simulation frame."""

    repo: Path
    processing: ModuleType
    benchmarking: ModuleType
    assets: dict[str, Any]
    asset_list: list[str]
    benchmark_beta: float
    attachment: float
    limit: float
    simulation: pd.DataFrame


def load_thesis(repo: str | Path) -> Thesis:
    """Load the thesis modules and prepare its simulation frame.

    ``benchmarking.py`` imports ``src.utils.formatting``; that module (numpy
    and pandas only) is loaded on its own and registered under that name, so
    nothing else of the thesis package is imported.

    Parameters
    ----------
    repo : str or pathlib.Path
        Thesis repository root.

    Returns
    -------
    Thesis
        Modules, settings and the notebook's ``transformed_simulation_df``.
    """
    root = Path(repo)
    for package in ("src", "src.utils"):
        if package not in sys.modules:
            stub = ModuleType(package)
            stub.__path__ = []  # a namespace for the submodule below
            sys.modules[package] = stub
    _load("src.utils.formatting", root / THESIS_FORMATTING)
    processing = _load("thesis_data_processing", root / THESIS_PROCESSING)
    benchmarking = _load("thesis_benchmarking", root / THESIS_BENCHMARKING)
    experiment = yaml.safe_load((root / THESIS_EXPERIMENT).read_text(encoding="utf-8"))
    settings = yaml.safe_load((root / THESIS_GLOBAL).read_text(encoding="utf-8"))
    assets = dict(experiment["ASSETS"])
    asset_list = list(assets)
    noise = experiment["NOISE_LAYER"]
    # The notebook's data preparation, cell by cell (implementation.ipynb).
    frame = pd.read_csv(root / THESIS_DATA)
    frame = processing.create_sub_portfolio(frame, asset_list)
    frame = processing.add_noise_to_asset_losses(
        df=frame,
        asset_data=asset_list,
        noise_level=noise["noise_value"],
        noise_type=noise["noise_type"],
        noise_reshuffel=noise["reshuffel"],
        random_seed=settings["RANDOM_SEED"],
    )
    frame = processing.calculate_portfolio_loss(df=frame, asset_list=asset_list)
    frame = processing.calculate_portfolio_max_wind(df=frame, asset_list=asset_list)
    frame = processing.calculate_annual_event_probabilities(
        df=frame, years=settings["N_YEARS"], noise_reshuffel=noise["reshuffel"]
    )
    frame = processing.delete_events_below_threshold(
        df=frame,
        threshold_column="Sub_Portfolio_Max_Wind",
        threshold_value=settings["ATTACHEMENT"],
    )
    return Thesis(
        repo=root,
        processing=processing,
        benchmarking=benchmarking,
        assets=assets,
        asset_list=asset_list,
        benchmark_beta=float(settings["BENCHMARK_BETA"]),
        attachment=float(settings["ATTACHEMENT"]),
        limit=float(settings["LIMIT"]),
        simulation=frame,
    )


def parse_printed_array(text: str) -> list[float]:
    r"""Parse an array the thesis CSV holds as numpy's ``str()`` output.

    Parameters
    ----------
    text : str
        E.g. ``"[0.00000000e+00 2.77558997e+03\\n 2.31563400e+04]"``.

    Returns
    -------
    list of float
        The numbers.

    Raises
    ------
    DerivationError
        If the text is not a bracketed list of numbers.
    """
    stripped = str(text).strip()
    if not (stripped.startswith("[") and stripped.endswith("]")):
        raise DerivationError(f"not a printed array: {stripped[:60]!r}")
    try:
        return [float(t) for t in stripped[1:-1].replace(",", " ").split()]
    except ValueError as exc:
        raise DerivationError(f"bad printed array {stripped[:60]!r}") from exc


def in_memory_rows(
    results: pd.DataFrame, attachment: float, limit: float, edge_atol: float = 1e-7
) -> pd.DataFrame:
    """Return golden results rows as the thesis notebook held them in memory.

    The notebook ran ``calculate_benchmarking_kpis`` on its in-memory
    results, whose ``Payouts`` and ``Breakpoints`` were numpy arrays; the CSV
    holds their ``str()`` prints, which the thesis' ``coerce_object_list``
    cannot parse. The payout levels are parsed from the prints (8
    significant digits, so recomputed KPIs can deviate from the golden ones
    in the ninth digit). The breakpoints are rebuilt with the thesis rule
    ``np.linspace(ATTACHEMENT, LIMIT, n_bins + 1)`` and must agree with the
    prints within ``edge_atol``.

    Parameters
    ----------
    results : pandas.DataFrame
        Rows of the golden results table.
    attachment, limit : float
        Thesis ``ATTACHEMENT`` and ``LIMIT``.
    edge_atol : float, default 1e-7
        Largest difference allowed between rebuilt and printed breakpoints.

    Returns
    -------
    pandas.DataFrame
        A copy with ``Payouts`` and ``Breakpoints`` as lists of floats.

    Raises
    ------
    DerivationError
        If a print is malformed or the breakpoints disagree.
    """
    frame = results.copy()
    payouts: list[list[float]] = []
    edges: list[list[float]] = []
    for row in frame.to_dict(orient="records"):
        levels = parse_printed_array(row["Payouts"])
        printed = np.array(parse_printed_array(row["Breakpoints"]))
        rebuilt = np.linspace(attachment, limit, len(levels) + 1)
        if (
            printed.shape != rebuilt.shape
            or np.abs(printed - rebuilt).max() > edge_atol
        ):
            raise DerivationError(
                f"breakpoints of {Record.from_row(row).label()} / {row['Asset_ID']} "
                "differ from the thesis rule"
            )
        payouts.append(levels)
        edges.append([float(x) for x in rebuilt])
    frame["Payouts"] = pd.Series(payouts, index=frame.index, dtype=object)
    frame["Breakpoints"] = pd.Series(edges, index=frame.index, dtype=object)
    return frame


def _record_rows(results: pd.DataFrame, record: Record) -> pd.DataFrame:
    keys = [Record.from_row(r) for r in results.to_dict(orient="records")]
    mask = np.array([k == record for k in keys], dtype=bool)
    return results.loc[mask]


def thesis_kpis(
    thesis: Thesis, rows: pd.DataFrame, beta: float
) -> dict[str, dict[str, float]]:
    """KPIs of one golden record by the thesis' ``calculate_benchmarking_kpis``.

    Parameters
    ----------
    thesis : Thesis
        From :func:`load_thesis`.
    rows : pandas.DataFrame
        The record's rows of the golden results table.
    beta : float
        ``benchmark_beta``.

    Returns
    -------
    dict
        KPI subject (asset, cluster or ``Portfolio``) to its KPI values. Empty
        if the thesis function skips the record (an entity is missing).
    """
    table = thesis.benchmarking.calculate_benchmarking_kpis(
        simulation_df=thesis.simulation,
        optimization_results=rows,
        assets_config=thesis.assets,
        benchmark_beta=beta,
        asset_list=thesis.asset_list,
    )
    return {
        str(r["Asset"]).strip(): {c: float(r[c]) for c in KPI_VALUE_COLUMNS}
        for r in table.to_dict(orient="records")
    }


def thesis_entity_kpis(
    thesis: Thesis, rows: pd.DataFrame, entity: str, beta: float
) -> dict[str, float]:
    """KPIs of one standard-scope entity by the thesis' own helpers.

    For records that ``calculate_benchmarking_kpis`` skips because an entity
    is missing: ``_build_standard_group_outputs`` then
    ``_calculate_entity_kpis``, as that function does for each entity.
    """
    bm = thesis.benchmarking
    frame = rows.copy()
    frame.columns = [c.strip().lower().replace(" ", "_") for c in frame.columns]
    coerce = sys.modules["src.utils.formatting"].coerce_object_list
    frame["payouts"] = frame["payouts"].apply(coerce)
    frame["breakpoints"] = frame["breakpoints"].apply(coerce)
    frame["included_assets_list"] = frame["included_assets"].apply(
        bm._normalize_included_assets
    )
    group = bm._build_standard_group_outputs(g=frame, simulation_df=thesis.simulation)
    probs = thesis.simulation["probability"].to_numpy(dtype=float)
    probs = probs / probs.sum()
    values = bm._calculate_entity_kpis(
        losses=group["loss_vectors"][entity],
        payouts=group["payout_vectors"][entity],
        probs=probs,
        beta=beta,
    )
    return {c: float(values[c]) for c in KPI_VALUE_COLUMNS}


def check_thesis_pipeline(
    thesis: Thesis,
    results: pd.DataFrame,
    kpis: pd.DataFrame,
    rtol: float,
    atol: float,
) -> dict[str, object]:
    """Recompute every golden KPI row with the thesis code; they must agree.

    The payout levels come from 8-significant-digit prints
    (:func:`in_memory_rows`), so the recomputed KPIs are not bit-identical:
    a value matches if ``|recomputed - golden| <= rtol |golden| + atol``.

    Parameters
    ----------
    thesis : Thesis
        From :func:`load_thesis`.
    results : pandas.DataFrame
        The golden results rows, from :func:`in_memory_rows`.
    kpis : pandas.DataFrame
        The golden KPI table.
    rtol, atol : float
        Tolerances.

    Returns
    -------
    dict
        ``values`` compared, ``max_rel_deviation`` over all of them and over
        the ``single_run`` records, ``values_above_1e-8`` (relative), and the
        tolerances.

    Raises
    ------
    DerivationError
        If a golden KPI row is not reproduced, or a value deviates by more
        than the tolerance.
    """
    recomputed = thesis.benchmarking.calculate_benchmarking_kpis(
        simulation_df=thesis.simulation,
        optimization_results=results,
        assets_config=thesis.assets,
        benchmark_beta=thesis.benchmark_beta,
        asset_list=thesis.asset_list,
    )
    ours = _kpi_rows(recomputed)
    golden = _kpi_rows(kpis)
    if set(ours) != set(golden):
        raise DerivationError(
            f"the thesis pipeline gives {len(ours)} KPI rows, the golden table "
            f"{len(golden)}"
        )
    worst = worst_single = 0.0
    compared = above = 0
    for key, want in golden.items():
        got = ours[key]
        for column in KPI_VALUE_COLUMNS:
            a, b = want[column], got[column]
            if math.isnan(a) and math.isnan(b):
                continue
            if math.isnan(a) or math.isnan(b) or not abs(a - b) <= rtol * abs(a) + atol:
                raise DerivationError(
                    f"thesis pipeline does not reproduce {key[0].label()} / "
                    f"{key[1]} / {column}: golden {a!r}, recomputed {b!r}"
                )
            dev = abs(a - b) / abs(a) if a != 0 else abs(b)
            compared += 1
            above += dev > 1e-8
            worst = max(worst, dev)
            if key[0].source == "single_run":
                worst_single = max(worst_single, dev)
    return {
        "kpi_rows": len(golden),
        "values": compared,
        "max_rel_deviation": worst,
        "max_rel_deviation_single_run": worst_single,
        "values_above_1e-8": above,
        "rtol": rtol,
        "atol": atol,
    }


def derive_with_thesis(
    thesis: Thesis,
    results: pd.DataFrame,
    items: Mapping[tuple[Record, str], str],
) -> tuple[list[dict[str, object]], dict[tuple[Record, str], str]]:
    """Rows of the (b) objectives, and the items the thesis code cannot give.

    Parameters
    ----------
    thesis : Thesis
        From :func:`load_thesis`.
    results : pandas.DataFrame
        The golden results table.
    items : mapping
        (record, problem) to KPI subject, from :func:`plan`.

    Returns
    -------
    rows : list of dict
        Output rows.
    missing : dict
        (record, problem) to the reason it is not compared.
    """
    by_record: dict[Record, list[tuple[str, str]]] = {}
    for (record, problem), subject in items.items():
        by_record.setdefault(record, []).append((problem, subject))
    rows: list[dict[str, object]] = []
    missing: dict[tuple[Record, str], str] = {}
    for record in sorted(by_record, key=Record.sort_key):
        record_rows = _record_rows(results, record)
        beta = record.beta if record.beta is not None else thesis.benchmark_beta
        table = thesis_kpis(thesis, record_rows, beta)
        for problem, subject in by_record[record]:
            how = f"thesis_kpis:{subject}@beta={beta:g}"
            values = table.get(subject)
            if values is None and record.approach == INDIVIDUAL:
                values = thesis_entity_kpis(thesis, record_rows, subject, beta)
                how = f"thesis_entity_kpis:{subject}@beta={beta:g}"
            if values is None:
                missing[(record, problem)] = (
                    "the thesis KPI code gives no row for this subject"
                )
                continue
            rows.append(
                {
                    **record.columns(),
                    "Problem": problem,
                    "Objective_Value": objective_from_kpis(
                        record.method, record.alpha, values
                    ),
                    "Derivation": RECOMPUTED,
                    "KPI_Source": how,
                }
            )
    return rows, missing


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


def to_frame(rows: Iterable[Mapping[str, object]]) -> pd.DataFrame:
    """Sorted output table (:data:`OUT_COLUMNS`)."""
    items = list(rows)
    items.sort(key=lambda r: (Record.from_row(r).sort_key(), str(r["Problem"])))
    return pd.DataFrame(items, columns=list(OUT_COLUMNS))


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    """Write the table with full float precision, deterministically."""
    frame.to_csv(path, index=False, lineterminator="\n")


def _not_compared(items: Mapping[tuple[Record, str], str]) -> list[dict[str, str]]:
    return [
        {"record": record.label(), "problem": problem, "reason": reason}
        for (record, problem), reason in sorted(
            items.items(), key=lambda kv: (kv[0][0].sort_key(), kv[0][1])
        )
    ]


def main(argv: Sequence[str] | None = None) -> int:
    """Derive the golden objectives and write the CSV and its provenance.

    Parameters
    ----------
    argv : sequence of str, optional
        Arguments (default: ``sys.argv[1:]``).

    Returns
    -------
    int
        0 on success.
    """
    parser = argparse.ArgumentParser(
        description="Build the golden objective table from the thesis outputs."
    )
    parser.add_argument("--thesis-repo", help="thesis repository root (read only)")
    parser.add_argument(
        "--a-only",
        action="store_true",
        help="derive only the rows that need no thesis code",
    )
    parser.add_argument("--results", default=str(RESULTS))
    parser.add_argument("--kpis", default=str(KPIS))
    parser.add_argument("--out-csv", default=str(OUT_CSV))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--benchmark-beta", type=float, default=0.95)
    parser.add_argument("--check-rtol", type=float, default=1e-5)
    parser.add_argument("--check-atol", type=float, default=1e-6)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    if args.thesis_repo is None and not args.a_only:
        parser.error("--thesis-repo is required (or pass --a-only)")
    out_csv, out_json = Path(args.out_csv), Path(args.out_json)
    for path in (out_csv, out_json):
        if path.exists() and not args.overwrite:
            parser.error(f"{path} exists; pass --overwrite")

    results, kpis = read_golden(Path(args.results), Path(args.kpis))
    decided = plan(results, kpis, args.benchmark_beta)
    rows = derive_from_kpis(kpis, decided.from_kpis)
    not_compared = dict(decided.not_compared)
    provenance: dict[str, Any] = {
        "description": "Golden objective values of the thesis design problems. "
        "Written by parity/scripts/derive_golden_objectives.py; "
        "the thesis wrote none, so each is derived (module docstring).",
        "inputs": {
            Path(args.results).name: sha256_file(args.results),
            Path(args.kpis).name: sha256_file(args.kpis),
        },
        "benchmark_beta": args.benchmark_beta,
        "formulas": dict(FORMULAS),
        "derivations": {
            DERIVED_FROM_KPIS: "from the committed golden KPI row of the "
            "problem's subject (KPI_Source golden:<subject>)",
            RECOMPUTED: "KPIs recomputed by the thesis benchmarking code at the "
            "record's Beta on the golden payouts and the thesis-prepared data "
            "(KPI_Source thesis_kpis:<subject>@beta=<b> from "
            "calculate_benchmarking_kpis, or thesis_entity_kpis:<subject>@beta=<b> "
            "from _build_standard_group_outputs + _calculate_entity_kpis for "
            "records the thesis dropped from its KPI table)",
        },
        "problems": {
            "individual_optimization": "one per asset; KPI subject = the asset",
            "cluster_optimization": "one joint problem 'portfolio'; KPI subject "
            "= Portfolio",
            "integrated_portfolio_optimization": "one joint problem "
            "'portfolio'; KPI subject = Portfolio",
        },
    }
    thesis_repo: str | None = args.thesis_repo
    if args.a_only or thesis_repo is None:
        for key in decided.by_thesis_code:
            not_compared[key] = "needs the thesis code (--a-only)"
    else:
        thesis = load_thesis(thesis_repo)
        memory = in_memory_rows(results, thesis.attachment, thesis.limit)
        provenance["thesis_check"] = check_thesis_pipeline(
            thesis, memory, kpis, args.check_rtol, args.check_atol
        )
        code_rows, missing = derive_with_thesis(thesis, memory, decided.by_thesis_code)
        rows.extend(code_rows)
        not_compared.update(missing)
        root = Path(thesis_repo)
        provenance["thesis_files"] = {
            name: sha256_file(root / name)
            for name in (
                THESIS_DATA,
                THESIS_EXPERIMENT,
                THESIS_GLOBAL,
                THESIS_FORMATTING,
                THESIS_PROCESSING,
                THESIS_BENCHMARKING,
            )
        }
    frame = to_frame(rows)
    write_csv(frame, out_csv)
    counts = frame["Derivation"].value_counts().to_dict()
    provenance["output"] = {
        "file": out_csv.name,
        "sha256": sha256_file(out_csv),
        "rows": len(frame),
        "by_derivation": {str(k): int(v) for k, v in sorted(counts.items())},
    }
    provenance["not_compared"] = _not_compared(not_compared)
    out_json.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"wrote {out_csv} ({len(frame)} rows: {provenance['output']['by_derivation']}),"
        f" {len(not_compared)} not compared"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
