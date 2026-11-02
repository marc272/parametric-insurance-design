r"""Run the thesis noise layer on the parity fixture and record digests.

The thesis function ``add_noise_to_asset_losses`` lives in
``src/utils/data_processing.py`` of the thesis repository
(``parametric-insurance-framework``). That file imports only numpy, pandas and
pathlib, so this script loads it in isolation with
:func:`importlib.util.spec_from_file_location`: the rest of the thesis
package (CLIMADA, cvxpy, plotting) is never imported, and nothing is added to
the environment.

The script feeds the function the parity EventSet
(``parity/tests/data/thesis_eventset``) in the thesis column layout
(``Event_ID``, ``Year``, ``A<k>_Wind``, ``A<k>_Loss``), with the thesis
parameters (seed 42, noise level 0.3, 13 copies, both noise types), and writes
the SHA256 of each noisy loss matrix to ``parity/golden/noise_digests.json``.
``parity/tests/test_noise_parity.py`` compares
``parametric_insurance_design.noise.add_noise`` against these digests without
the thesis repository, and against the thesis function itself when
``PARITY_THESIS_REPO`` is set.

Run from the repository root::

    uv run python parity/scripts/thesis_noise_digests.py \
        --thesis-repo ../parametric-insurance-framework --overwrite

The thesis repository is only read, never modified.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import numpy as np
import pandas as pd

from parametric_insurance_design.eventset import EventSet

PARITY_DIR = Path(__file__).resolve().parents[1]
EVENTSET_DIR = PARITY_DIR / "tests" / "data" / "thesis_eventset"
DIGESTS = PARITY_DIR / "golden" / "noise_digests.json"
CONVERT_SCRIPT = PARITY_DIR / "scripts" / "convert_thesis_eventset.py"

THESIS_REPO_ENV = "PARITY_THESIS_REPO"
THESIS_MODULE = "src/utils/data_processing.py"
THESIS_FUNCTION = "add_noise_to_asset_losses"

# Thesis parameters: configs/global_settings.yaml (RANDOM_SEED, ATTACHEMENT,
# LIMIT) and configs/experiment_config.yaml (NOISE_LAYER).
SEED = 42
LEVEL = 0.3
N_COPIES = 13
BOUNDS = (20.0, 70.0)
KINDS = ("heteroscedastic", "homoscedastic")
N_TOP = 32
N_SPREAD = 128
SUMMARY_RTOL = 1e-12
THESIS_KIND = "heteroscedastic"


def load_thesis_module(repo: str | Path) -> ModuleType:
    """Load the thesis ``data_processing`` module on its own.

    Parameters
    ----------
    repo : str or pathlib.Path
        Thesis repository root.

    Returns
    -------
    types.ModuleType
        The module, registered as ``thesis_data_processing``.

    Raises
    ------
    FileNotFoundError
        If the repository lacks :data:`THESIS_MODULE`.
    """
    path = Path(repo) / THESIS_MODULE
    if not path.is_file():
        raise FileNotFoundError(f"{repo} does not hold {THESIS_MODULE}")
    spec = importlib.util.spec_from_file_location("thesis_data_processing", path)
    if spec is None or spec.loader is None:  # pragma: no cover - importlib quirk
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def thesis_frame(eventset: EventSet) -> pd.DataFrame:
    """Return an EventSet in the thesis wide layout.

    Parameters
    ----------
    eventset : EventSet
        EventSet without draws.

    Returns
    -------
    pandas.DataFrame
        ``Event_ID``, ``Year``, then ``<id>_Wind`` and ``<id>_Loss`` per
        location, in EventSet row and location order.
    """
    columns: dict[str, Any] = {
        "Event_ID": eventset.events["event_id"].to_numpy(),
        "Year": eventset.events["year"].to_numpy(),
    }
    for j, location in enumerate(eventset.location_ids):
        columns[f"{location}_Wind"] = eventset.index[:, j]
        columns[f"{location}_Loss"] = eventset.loss[:, j]
    return pd.DataFrame(columns)


def run_thesis(
    module: ModuleType, eventset: EventSet, kind: str, *, seed: int = SEED
) -> pd.DataFrame:
    """Run the thesis noise function on an EventSet.

    Parameters
    ----------
    module : types.ModuleType
        The module from :func:`load_thesis_module`.
    eventset : EventSet
        EventSet without draws.
    kind : str
        Thesis ``noise_type``.
    seed : int, default SEED
        Thesis ``random_seed``.

    Returns
    -------
    pandas.DataFrame
        The thesis output: the expanded frame with noisy ``<id>_Loss``
        columns and ``noise_sample_id``.
    """
    function = getattr(module, THESIS_FUNCTION)
    return function(
        df=thesis_frame(eventset),
        asset_data=eventset.location_ids,
        noise_level=LEVEL,
        noise_type=kind,
        random_seed=seed,
        noise_reshuffel=N_COPIES,
    )


def thesis_losses(frame: pd.DataFrame, location_ids: Sequence[str]) -> np.ndarray:
    """Return the ``<id>_Loss`` columns of a thesis frame as a matrix."""
    return frame[[f"{loc}_Loss" for loc in location_ids]].to_numpy(dtype=np.float64)


def matrix_digest(matrix: np.ndarray) -> str:
    """Return the SHA256 of a float64 matrix's C-order little-endian bytes.

    Parameters
    ----------
    matrix : numpy.ndarray
        Two-dimensional float64 array.

    Returns
    -------
    str
        Lower-case hex digest.
    """
    data = np.ascontiguousarray(matrix, dtype="<f8")
    return hashlib.sha256(data.tobytes()).hexdigest()


def matrix_summary(matrix: np.ndarray) -> dict[str, Any]:
    """Return a platform-robust summary of a noisy loss matrix.

    The bits of the noisy losses depend on the platform's ``exp`` and ``log``
    (numpy picks SIMD or libm implementations by CPU), so the SHA256 only
    matches on the platform that wrote it. The summary is compared with a
    tight relative tolerance instead: any change in the random stream, the
    call order or the expansion changes it by far more.

    Parameters
    ----------
    matrix : numpy.ndarray
        Two-dimensional float64 array.

    Returns
    -------
    dict
        ``column_sums`` (one per location) and ``samples``: ``[row, column,
        value]`` for the :data:`N_TOP` largest entries and :data:`N_SPREAD`
        evenly spaced positive entries (row-major order).
    """
    flat = matrix.ravel()
    positive = np.flatnonzero(flat > 0)
    spread = positive[np.linspace(0, len(positive) - 1, N_SPREAD).astype(np.int64)]
    top = np.argsort(-flat, kind="stable")[:N_TOP]
    picks = np.unique(np.concatenate([top, spread]))
    n_columns = matrix.shape[1]
    return {
        "column_sums": [float(v) for v in matrix.sum(axis=0)],
        "samples": [
            [int(k // n_columns), int(k % n_columns), float(flat[k])] for k in picks
        ],
    }


def summary_deviation(summary: dict[str, Any], matrix: np.ndarray) -> float:
    """Return the largest relative deviation of a matrix from a summary.

    Parameters
    ----------
    summary : dict
        A :func:`matrix_summary` record.
    matrix : numpy.ndarray
        Noisy loss matrix to compare.

    Returns
    -------
    float
        ``max |actual - expected| / |expected|`` over the column sums and the
        sampled entries.
    """
    expected = np.array(
        [*summary["column_sums"], *(value for _, _, value in summary["samples"])]
    )
    rows = [int(r) for r, _, _ in summary["samples"]]
    columns = [int(c) for _, c, _ in summary["samples"]]
    actual = np.concatenate([matrix.sum(axis=0), matrix[rows, columns]])
    return float(np.max(np.abs(actual - expected) / np.abs(expected)))


def same_platform(record: dict[str, Any]) -> bool:
    """Tell whether this interpreter matches the platform that wrote a record.

    Parameters
    ----------
    record : dict
        Content of :data:`DIGESTS`.

    Returns
    -------
    bool
        True if the operating system, machine and numpy version match
        ``record["generated_with"]``.
    """
    made = record["generated_with"]
    return (made["system"], made["machine"], made["numpy"]) == (
        platform.system(),
        platform.machine(),
        np.__version__,
    )


def sha256_file(path: str | Path) -> str:
    """Return the SHA256 hex digest of a file.

    Parameters
    ----------
    path : str or pathlib.Path
        File to hash.

    Returns
    -------
    str
        Lower-case hex digest.
    """
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_convert_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "convert_thesis_eventset", CONVERT_SCRIPT
    )
    if spec is None or spec.loader is None:  # pragma: no cover - importlib quirk
        raise ImportError(f"cannot load {CONVERT_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses need the module registered
    spec.loader.exec_module(module)
    return module


def build_digests(repo: Path) -> dict[str, Any]:
    """Run the thesis function and return the content of the digest file.

    Parameters
    ----------
    repo : pathlib.Path
        Thesis repository root.

    Returns
    -------
    dict
        JSON-serialisable record of the inputs, parameters and digests.
    """
    conv = _load_convert_script()
    module = load_thesis_module(repo)
    eventset = EventSet.from_parquet(EVENTSET_DIR)
    digests: dict[str, Any] = {}
    for kind in KINDS:
        losses = thesis_losses(
            run_thesis(module, eventset, kind), eventset.location_ids
        )
        digests[kind] = {
            "loss_sha256": matrix_digest(losses),
            "shape": list(losses.shape),
            "summary": matrix_summary(losses),
        }
    return {
        "description": (
            "SHA256 of the noisy loss matrix that the thesis function "
            f"{THESIS_FUNCTION} ({THESIS_MODULE}) returns on the parity "
            "EventSet: rows in the thesis expansion order (event-major, "
            "noise_sample_id 0..n_copies-1), columns in location order, "
            "float64 little-endian bytes in C order. The bits depend on the "
            "platform's exp/log (see generated_with), so the summary (column "
            f"sums and sampled entries) is the cross-platform check, at rtol "
            f"{SUMMARY_RTOL}. Written by "
            "parity/scripts/thesis_noise_digests.py; checked by "
            "parity/tests/test_noise_parity.py."
        ),
        "thesis_repo": conv.THESIS_REPO_URL,
        "thesis_commit": conv.thesis_commit(repo),
        "thesis_module_sha256": sha256_file(repo / THESIS_MODULE),
        "eventset": {
            "path": "tests/data/thesis_eventset",
            "files_sha256": {
                name: sha256_file(EVENTSET_DIR / name)
                for name in ("events.parquet", "values.parquet")
            },
        },
        "parameters": {
            "random_seed": SEED,
            "noise_level": LEVEL,
            "noise_reshuffel": N_COPIES,
            "heteroscedastic_bounds": list(BOUNDS),
            "asset_order": eventset.location_ids,
        },
        "generated_with": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "machine": platform.machine(),
            "system": platform.system(),
        },
        "digests": digests,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Write :data:`DIGESTS` from a thesis checkout.

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
    parser.add_argument("--output", type=Path, default=DIGESTS)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    if args.thesis_repo is None:
        parser.error(f"pass --thesis-repo or set {THESIS_REPO_ENV}")
    if args.output.exists() and not args.overwrite:
        raise FileExistsError(f"{args.output} exists; pass --overwrite")
    record = build_digests(Path(args.thesis_repo).expanduser().resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
