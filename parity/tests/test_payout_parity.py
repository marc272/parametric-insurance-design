"""Parity of ``payout.StepPayout`` with the thesis step payout (MAR-11).

The thesis maps index values to bins in two places, with the same rule:

- ``OptimizationConstructor._mapping`` (``src/implementation.ipynb``) builds the
  basis matrix of the optimisation;
- ``get_payout_for_asset`` (``src/utils/benchmarking.py``) evaluates a fitted
  payout for the KPIs.

Rule: clip to ``[b_0, b_n - 1e-12]``, then ``searchsorted(side="right") - 1``.
So bins are ``[b_k, b_{k+1})``, values below the attachment go to bin 0 and
values at or above the limit go to the last bin. Breakpoints are
``np.linspace(attachment, limit, n_bins + 1)`` with attachment 20 and limit 70
(``configs/global_settings.yaml``).

Two groups:

- Checks on the committed fixture (``tests/data/thesis_eventset``) and golden
  table, against expectations derived by hand from the rule above. They need
  nothing outside this repository.
- Checks against the thesis functions themselves, bit for bit. They run when
  ``PARITY_THESIS_REPO`` points at a checkout of
  ``parametric-insurance-framework`` and are skipped, with that reason,
  otherwise. The functions are read from the thesis sources with ``ast`` and
  executed on their own, so nothing else from the thesis is imported.
"""

from __future__ import annotations

import ast
import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.payout import (
    THESIS_UPPER_EPS,
    StepPayout,
    uniform_breakpoints,
)

PARITY_DIR = Path(__file__).resolve().parents[1]
EVENTSET_DIR = PARITY_DIR / "tests" / "data" / "thesis_eventset"
GOLDEN_RESULTS = PARITY_DIR / "golden" / "full_optimization_results.csv.gz"

THESIS_REPO_ENV = "PARITY_THESIS_REPO"  # as in test_thesis_eventset.py (MAR-9)
THESIS_REPO_URL = "https://github.com/marc272/parametric-insurance-framework"
THESIS_NOTEBOOK = "src/implementation.ipynb"
THESIS_BENCHMARKING = "src/utils/benchmarking.py"

ATTACHMENT = 20.0  # thesis ATTACHEMENT
LIMIT = 70.0  # thesis LIMIT
N_BINS_USED = (5, 10, 15, 20, 25)  # every N_Bins in the golden results
N_GOLDEN_ROWS = 1551
N_CELLS = 6057 * 9
N_ZERO_CELLS = 44_659
N_BELOW_ATTACHMENT_POSITIVE = 1904  # 0 < wind < 20 (CLIMADA keeps >= 17.5)
N_AT_OR_ABOVE_LIMIT = 5

# Index values on and around every kind of edge, for the bit-for-bit checks.
EDGE_VALUES = np.array(
    [
        -1e6,
        -1.0,
        0.0,
        17.5,
        np.nextafter(ATTACHMENT, -np.inf),
        ATTACHMENT,
        np.nextafter(ATTACHMENT, np.inf),
        *np.linspace(ATTACHMENT, LIMIT, 101),
        *np.nextafter(np.linspace(ATTACHMENT, LIMIT, 101), -np.inf),
        *np.nextafter(np.linspace(ATTACHMENT, LIMIT, 101), np.inf),
        LIMIT - THESIS_UPPER_EPS,
        LIMIT - THESIS_UPPER_EPS / 2,
        np.nextafter(LIMIT, -np.inf),
        LIMIT,
        np.nextafter(LIMIT, np.inf),
        71.61326806929178,
        1e6,
    ]
)


def _parse_vector(text: str) -> np.ndarray:
    """Parse a numpy-printed vector such as ``'[20. 30.\\n 40.]'``."""
    return np.array(text.strip().strip("[]").split(), dtype=np.float64)


@pytest.fixture(scope="module")
def eventset() -> EventSet:
    return EventSet.from_parquet(EVENTSET_DIR)


@pytest.fixture(scope="module")
def golden() -> pd.DataFrame:
    table = pd.read_csv(GOLDEN_RESULTS)
    assert len(table) == N_GOLDEN_ROWS
    return table


def _golden_rows(
    golden: pd.DataFrame, eventset: EventSet
) -> Iterator[tuple[int, np.ndarray, np.ndarray, int]]:
    """Yield ``(row, entity index, payout levels, n_bins)`` for every result.

    The entity index of an asset is its wind; of a cluster, the value-weighted
    mean wind of its assets, computed as the thesis
    ``_build_cluster_group_outputs`` does.
    """
    columns = {loc: k for k, loc in enumerate(eventset.location_ids)}
    values = dict(
        zip(
            eventset.locations["location_id"].tolist(),
            eventset.locations["value"].tolist(),
            strict=True,
        )
    )
    records = zip(
        golden["Asset_ID"].astype(str).str.strip().tolist(),
        golden["Included_Assets"].astype(str).tolist(),
        golden["Payouts"].astype(str).tolist(),
        golden["N_Bins"].astype(int).tolist(),
        strict=True,
    )
    for row, (entity, included, payouts, n_bins) in enumerate(records):
        if entity in columns:
            xi = eventset.index[:, columns[entity]]
        else:
            assets = ast.literal_eval(included)
            weights = np.asarray([float(values[a]) for a in assets], dtype=float)
            weights = weights / weights.sum()
            winds = np.vstack([eventset.index[:, columns[a]] for a in assets])
            xi = np.sum(winds * weights[:, None], axis=0)
        yield row, xi, _parse_vector(payouts), int(n_bins)


def _hand_bins(x: np.ndarray, n_bins: int) -> np.ndarray:
    """Bin of each value by arithmetic, independent of the implementation.

    Bin width ``w = (LIMIT - ATTACHMENT) / n_bins``; bin ``floor((x - 20) /
    w)``, with everything below 20 in bin 0 and everything at or above 70 in
    the last bin. Only valid for values well away from the breakpoints, which
    the callers check.
    """
    width = (LIMIT - ATTACHMENT) / n_bins
    return np.clip(np.floor((x - ATTACHMENT) / width), 0, n_bins - 1).astype(int)


def _distance_to_breakpoints(x: np.ndarray, n_bins: int) -> float:
    edges = uniform_breakpoints(ATTACHMENT, LIMIT, n_bins)
    return float(np.min(np.abs(x.ravel()[:, None] - edges[None, :])))


# -- committed fixture and golden table (no thesis repository needed) ---------


def test_golden_breakpoints_are_uniform_on_attachment_limit(
    golden: pd.DataFrame,
) -> None:
    assert sorted(golden["N_Bins"].unique().tolist()) == list(N_BINS_USED)
    records = zip(
        golden["N_Bins"].astype(int).tolist(),
        golden["Breakpoints"].astype(str).tolist(),
        golden["Payouts"].astype(str).tolist(),
        strict=True,
    )
    for n_bins, breakpoints, payouts in records:
        printed = _parse_vector(breakpoints)  # 8 decimals in the CSV
        ours = StepPayout(ATTACHMENT, LIMIT, n_bins).edges
        assert printed.shape == ours.shape == (n_bins + 1,)
        assert (printed[0], printed[-1]) == (ATTACHMENT, LIMIT)
        np.testing.assert_allclose(printed, ours, rtol=0, atol=5e-9)
        assert _parse_vector(payouts).shape == (n_bins,)


def test_fixture_out_of_range_values_clip_into_end_bins(eventset: EventSet) -> None:
    x = eventset.index
    assert x.size == N_CELLS
    zero = x == 0
    below = (x > 0) & (x < ATTACHMENT)
    above = x >= LIMIT
    assert int(zero.sum()) == N_ZERO_CELLS
    assert int(below.sum()) == N_BELOW_ATTACHMENT_POSITIVE
    assert int(above.sum()) == N_AT_OR_ABOVE_LIMIT
    # The strongest wind in the fixture: storm NA_5114_0 at A2, 71.6 m/s.
    row, col = np.unravel_index(np.argmax(x), x.shape)
    assert eventset.events["event_id"].iloc[row] == "NA_5114_0"
    assert eventset.location_ids[col] == "A2"
    assert x[row, col] == pytest.approx(71.61326806929178, abs=0)
    for n_bins in N_BINS_USED:
        k = StepPayout(ATTACHMENT, LIMIT, n_bins).bin_index(x)
        assert (k[zero | below] == 0).all()
        assert (k[above] == n_bins - 1).all()
        assert k[row, col] == n_bins - 1


@pytest.mark.parametrize("n_bins", N_BINS_USED)
def test_fixture_bins_match_hand_derivation(eventset: EventSet, n_bins: int) -> None:
    x = eventset.index
    # No fixture wind lies on or within 1e-6 m/s of a breakpoint, so the
    # floor formula and the half-open bins cannot disagree by rounding.
    assert _distance_to_breakpoints(x, n_bins) > 1e-6
    payout = StepPayout(ATTACHMENT, LIMIT, n_bins)
    expected = _hand_bins(x, n_bins)
    np.testing.assert_array_equal(payout.bin_index(x), expected)
    for j in range(x.shape[1]):
        m = payout.basis_matrix(x[:, j])
        np.testing.assert_array_equal(m.sum(axis=1), 1.0)
        np.testing.assert_array_equal(np.argmax(m, axis=1), expected[:, j])


def test_fixture_bin_counts_for_the_thesis_default(eventset: EventSet) -> None:
    # 15 bins of width 10/3 m/s on [20, 70]: the thesis single-run setting.
    # Rows per bin for A1, derived with the floor formula above.
    x = eventset.index[:, 0]
    counts = np.bincount(StepPayout(ATTACHMENT, LIMIT, 15).bin_index(x), minlength=15)
    assert counts.sum() == x.size
    expected = np.bincount(_hand_bins(x, 15), minlength=15)
    np.testing.assert_array_equal(counts, expected)
    # Bin 0 holds the 5,172 rows below 20 m/s plus those in [20, 23.33).
    assert counts[0] == int((x < 20).sum()) + int(((x >= 20) & (x < 70 / 3)).sum())
    assert int((x < 20).sum()) == 5172


def test_golden_payouts_on_fixture_match_hand_derivation(
    golden: pd.DataFrame, eventset: EventSet
) -> None:
    n_checked = 0
    for _, xi, levels, n_bins in _golden_rows(golden, eventset):
        payout = StepPayout(ATTACHMENT, LIMIT, n_bins)
        assert _distance_to_breakpoints(xi, n_bins) > 1e-9
        got = payout.evaluate(xi[:, None], levels[None, :])[:, 0]
        np.testing.assert_array_equal(got, levels[_hand_bins(xi, n_bins)])
        # Zero-wind rows pay the first level (thesis clipping, not 0).
        np.testing.assert_array_equal(got[xi == 0], levels[0])
        n_checked += 1
    assert n_checked == N_GOLDEN_ROWS


# -- against the thesis functions (local only) --------------------------------


def _load_function(
    source: str, *, name: str, cls: str | None = None
) -> Callable[..., Any]:
    """Compile one function from thesis source text, without its module.

    The function is executed in a namespace holding only ``np``, so the rest
    of the thesis module (imports, globals) is never run.
    """
    tree = ast.parse(source)
    scope: list[ast.stmt] = tree.body
    if cls is not None:
        classes = [
            n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls
        ]
        assert len(classes) == 1, f"class {cls} not found exactly once"
        scope = classes[0].body
    found = [n for n in scope if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(found) == 1, f"function {name} not found exactly once"
    function = found[0]
    function.decorator_list = []  # drop @staticmethod
    module = ast.Module(body=[function], type_ignores=[])
    namespace: dict[str, Any] = {"np": np}
    exec(compile(module, f"<thesis {name}>", "exec"), namespace)
    return namespace[name]


@pytest.fixture(scope="module")
def thesis_repo() -> Path:
    value = os.environ.get(THESIS_REPO_ENV)
    if not value:
        pytest.skip(
            f"{THESIS_REPO_ENV} is not set; set it to a checkout of "
            f"{THESIS_REPO_URL} to compare with the thesis _mapping and "
            "get_payout_for_asset"
        )
    repo = Path(value).expanduser()
    for rel in (THESIS_NOTEBOOK, THESIS_BENCHMARKING):
        if not (repo / rel).is_file():
            pytest.fail(f"{THESIS_REPO_ENV}={value} does not hold {rel}")
    return repo


@pytest.fixture(scope="module")
def thesis(thesis_repo: Path) -> dict[str, Callable[..., Any]]:
    notebook = json.loads((thesis_repo / THESIS_NOTEBOOK).read_text(encoding="utf-8"))
    cells = [
        "".join(cell["source"])
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
        and "class OptimizationConstructor" in "".join(cell["source"])
    ]
    assert len(cells) == 1, "OptimizationConstructor not found in exactly one cell"
    benchmarking = (thesis_repo / THESIS_BENCHMARKING).read_text(encoding="utf-8")
    return {
        "_mapping": _load_function(
            cells[0], name="_mapping", cls="OptimizationConstructor"
        ),
        "_breakpoints": _load_function(
            cells[0], name="_breakpoints", cls="OptimizationConstructor"
        ),
        "get_payout_for_asset": _load_function(
            benchmarking, name="get_payout_for_asset"
        ),
    }


@pytest.mark.parametrize("n_bins", range(1, 31))
def test_thesis_breakpoints_identical(
    thesis: dict[str, Callable[..., Any]], n_bins: int
) -> None:
    theirs = thesis["_breakpoints"](None, n_bins, ATTACHMENT, LIMIT)
    ours = uniform_breakpoints(ATTACHMENT, LIMIT, n_bins)
    assert ours.dtype == theirs.dtype
    np.testing.assert_array_equal(ours, theirs, strict=True)
    np.testing.assert_array_equal(StepPayout(ATTACHMENT, LIMIT, n_bins).edges, theirs)


@pytest.mark.parametrize("n_bins", N_BINS_USED)
def test_thesis_mapping_identical_on_fixture(
    thesis: dict[str, Callable[..., Any]], eventset: EventSet, n_bins: int
) -> None:
    payout = StepPayout(ATTACHMENT, LIMIT, n_bins)
    for j in range(eventset.n_locations):
        x = eventset.index[:, j]
        theirs = thesis["_mapping"](x, payout.edges)
        np.testing.assert_array_equal(payout.basis_matrix(x), theirs, strict=True)


@pytest.mark.parametrize("n_bins", [1, 2, 3, *N_BINS_USED, 50, 100])
def test_thesis_mapping_and_payout_identical_on_edges(
    thesis: dict[str, Callable[..., Any]], n_bins: int
) -> None:
    payout = StepPayout(ATTACHMENT, LIMIT, n_bins)
    edges = payout.edges
    values = np.concatenate(
        [EDGE_VALUES, edges, np.nextafter(edges, -np.inf), np.nextafter(edges, np.inf)]
    )
    np.testing.assert_array_equal(
        payout.basis_matrix(values), thesis["_mapping"](values, edges), strict=True
    )
    levels = np.arange(1.0, n_bins + 1.0)
    np.testing.assert_array_equal(
        payout.evaluate(values[:, None], levels[None, :])[:, 0],
        thesis["get_payout_for_asset"](values, levels, edges),
        strict=True,
    )


def test_thesis_payout_identical_on_golden_results(
    thesis: dict[str, Callable[..., Any]],
    golden: pd.DataFrame,
    eventset: EventSet,
) -> None:
    n_checked = 0
    for _, xi, levels, n_bins in _golden_rows(golden, eventset):
        payout = StepPayout(ATTACHMENT, LIMIT, n_bins)
        theirs = thesis["get_payout_for_asset"](xi, levels, payout.edges)
        ours = payout.evaluate(xi[:, None], levels[None, :])[:, 0]
        np.testing.assert_array_equal(ours, theirs, strict=True)
        np.testing.assert_array_equal(
            payout.basis_matrix(xi), thesis["_mapping"](xi, payout.edges), strict=True
        )
        n_checked += 1
    assert n_checked == N_GOLDEN_ROWS


def test_thesis_mapping_fails_where_we_clamp(
    thesis: dict[str, Callable[..., Any]],
) -> None:
    # Where limit - 1e-12 rounds back to the limit, _mapping indexes past its
    # last column. get_payout_for_asset clamps to the last bin; so do we.
    limit = 2.0**15
    payout = StepPayout(0.0, limit, 4)
    values = np.array([0.0, limit, 2 * limit])
    with pytest.raises(IndexError):
        thesis["_mapping"](values, payout.edges)
    levels = np.array([1.0, 2.0, 3.0, 4.0])
    np.testing.assert_array_equal(
        payout.evaluate(values[:, None], levels[None, :])[:, 0],
        thesis["get_payout_for_asset"](values, levels, payout.edges),
    )
    np.testing.assert_array_equal(payout.bin_index(values), [0, 3, 3])
