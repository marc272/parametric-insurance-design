"""Tests for the CLIMADA module's golden fixtures, ``parity/climada/`` (MAR-312).

Three groups:

- **Regeneration.** ``parity/scripts/export_climada_fixtures.py`` rebuilds the
  set in memory from the core, and the committed files must pass
  ``compare_case`` against it. A non-unique design is judged by what holds for
  every point of its optimal set, so a solver that returns another point (on
  another platform) does not fail the check.
- **The files.** Canonical text, the 200 KB limit, the case matrix, the shared
  samples, the licence records and the tolerance, stated once.
- **A reader without our code.** Each case is read with plain numpy and the
  rules of ``parity/climada/README.md`` only (no core, no script): the payouts
  of the written cover, the objective, the premium, the budget, the constraints
  and every listed metric are recomputed and must match. The LP designs are
  also solved again from ADR 0006 §5.1 and §6 with scipy's HiGHS. This is what
  the module's tests in the fork do.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import math
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pytest
from scipy.optimize import linprog

PARITY_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PARITY_DIR.parent
SCRIPT = PARITY_DIR / "scripts" / "export_climada_fixtures.py"
SET_DIR = PARITY_DIR / "climada"
CASES_DIR = SET_DIR / "cases"
SAMPLES_DIR = SET_DIR / "samples"
README = SET_DIR / "README.md"
MAX_TOTAL_BYTES = 200_000
"""ADR 0006 §12: at most 200 KB for the whole set."""
TOLERANCE = 1e-6
"""ADR 0006 §12, the contract's tolerance."""
VAR_ROUNDING = 1e-10
"""ADR 0006 §7: a level on a step gives the lower atom, allowing this much."""

# The case matrix, stated here independently of the script.
OBJECTIVES = ("mse", "eu", "wcvar-b0_9")
PRICINGS = ("pure", "coc")
SCOPES = ("individual", "joint")
CORE_BASES = (("annual", "s1"), ("event", "s2"))
FAMILIES = ("linear", "piecewise-linear", "binary")
CORE_CASES = {
    *(
        f"step-{o}-{p}-{b}-{s}-{d}"
        for o in OBJECTIVES
        for p in PRICINGS
        for s in SCOPES
        for b, d in CORE_BASES
    ),
    "step-wcvar-b0_99-pure-annual-joint-s1",
}
CLOSED_FORM_CASES = {
    *(f"{f}-fixed-pure-annual-individual-h1" for f in FAMILIES),
    *(f"{f}-fixed-coc-event-individual-h1" for f in FAMILIES),
    "step-fixed-pure-event-individual-h2",
    "linear-fixed-pure-event-individual-h2",
    "piecewise-linear-fixed-coc-event-individual-h2",
    "binary-fixed-pure-event-individual-h2",
    "linear-fixed-pure-annual-joint-s1",
    "step-fixed-coc-event-joint-h3",
    *(
        f"{f}-lower-fixed-pure-annual-individual-h4"
        for f in ("step", "linear", "piecewise-linear", "binary")
    ),
    "binary-mse-pure-annual-individual-h1",
    "binary-wcvar-b0_9-coc-event-individual-h2",
    "binary-eu-pure-event-individual-h2",
    "linear-eu-pure-annual-individual-h1",
    "linear-mse-coc-event-individual-h2",
    "linear-wcvar-b0_9-pure-event-individual-h1",
    "piecewise-linear-mse-pure-annual-individual-h5",
}
EXPECTED_CASES = CORE_CASES | CLOSED_FORM_CASES
EXPECTED_SAMPLES = {"s1", "s2", "h1", "h2", "h3", "h4", "h5"}
CASE_FIELDS = {
    "case_id",
    "kind",
    "source",
    "sample",
    "basis",
    "scope",
    "cover",
    "objective",
    "pricing",
    "budget",
    "limit",
    "expected",
    "compare_parameters",
    "tolerances",
    "generator",
}
SAMPLE_FIELDS = {
    "event_id",
    "frequency",
    "year",
    "parent",
    "unit_id",
    "index",
    "loss",
    "index_unit",
    "loss_unit",
    "licence",
}
EXPECTED_FIELDS = {
    "objective_value",
    "premium",
    "parameters",
    "unidentified",
    "unique",
    "metrics",
}
UNITLESS = (
    "coverage_ratio",
    "payout_to_loss_ratio",
    "payout_frequency",
    "correlation",
    "tail_coverage_",
    "cvar_uncovered_to_loss_",
    "false_negative_rate_",
    "false_positive_rate_",
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("export_climada_fixtures", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses need the module registered
    spec.loader.exec_module(module)
    return module


exporter = _load_script()

# Another platform's solvers can return another point of a set of optimal
# designs. The local proxy: Clarabel without equilibration and HiGHS's primal
# simplex, both still accurate.
PERTURBED = exporter.SolverSettings(
    accurate=exporter.SolverPolicy(
        lp_solvers=("CLARABEL",),
        qp_solvers=("CLARABEL",),
        accept_inaccurate=False,
        solver_options={
            "CLARABEL": {**exporter.CLARABEL_TIGHT, "equilibrate_enable": False}
        },
    ),
    vertex=exporter.SolverPolicy(
        lp_solvers=("HIGHS",),
        qp_solvers=("CLARABEL",),
        accept_inaccurate=False,
        solver_options={"HIGHS": {"simplex_strategy": 4}},
    ),
    ranging={**exporter.HIGHS_RANGING_OPTIONS, "simplex_strategy": 4},
)


def _read_all(folder: Path) -> dict[str, dict[str, Any]]:
    return {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(folder.glob("*.json"))
    }


@pytest.fixture(scope="module")
def fixtures() -> Any:  # noqa: ANN401
    return exporter.build_set()


@pytest.fixture(scope="module")
def cases() -> dict[str, dict[str, Any]]:
    return _read_all(CASES_DIR)


@pytest.fixture(scope="module")
def samples() -> dict[str, dict[str, Any]]:
    return _read_all(SAMPLES_DIR)


def _sample_of(
    case: dict[str, Any], samples: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    return samples[Path(case["sample"]).stem]


# --------------------------------------------------------------------------
# Regeneration
# --------------------------------------------------------------------------


def test_regeneration_matches_the_committed_set(fixtures: Any) -> None:  # noqa: ANN401
    committed_cases = _read_all(CASES_DIR)
    committed_samples = _read_all(SAMPLES_DIR)
    assert set(committed_cases) == {n.removesuffix(".json") for n in fixtures.cases}
    assert set(committed_samples) == {n.removesuffix(".json") for n in fixtures.samples}
    problems: list[str] = []
    for name, doc in fixtures.samples.items():
        got = committed_samples[name.removesuffix(".json")]
        problems += [f"{name}: {d}" for d in exporter.compare_documents(got, doc, 1.0)]
    for name, case in fixtures.cases.items():
        got = committed_cases[name.removesuffix(".json")]
        problems += [f"{name}: {d}" for d in exporter.compare_case(got, case)]
    assert not problems, "\n".join(problems[:30])


def test_regeneration_check_holds_with_other_solver_points() -> None:
    other = exporter.build_set(commit="x", settings=PERTURBED)
    committed = _read_all(CASES_DIR)
    problems: list[str] = []
    for name, case in other.cases.items():
        diffs = exporter.compare_case(committed[name.removesuffix(".json")], case)
        problems += [f"{name}: {d}" for d in diffs]
    assert not problems, "\n".join(problems[:30])


def test_regeneration_is_byte_stable_on_one_machine(fixtures: Any) -> None:  # noqa: ANN401
    again = exporter.build_set(commit=exporter.core_commit())
    assert exporter.texts_of(again) == exporter.texts_of(fixtures)


def _copy(doc: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(doc))


def _a_non_unique_lp(fixtures: Any) -> tuple[str, Any]:  # noqa: ANN401
    name = "step-eu-pure-annual-joint-s1.json"
    return name, fixtures.cases[name]


def test_compare_case_rejects_levels_outside_the_optimal_set(
    fixtures: Any,  # noqa: ANN401
    cases: dict[str, dict[str, Any]],
) -> None:
    name, generated = _a_non_unique_lp(fixtures)
    doc = _copy(cases[name.removesuffix(".json")])
    levels = doc["expected"]["parameters"]["u1"]
    levels["levels[2]"] = 1.5 * levels["levels[2]"]
    assert exporter.compare_case(doc, generated)


def test_compare_case_rejects_values_that_are_not_the_cores(
    fixtures: Any,  # noqa: ANN401
    cases: dict[str, dict[str, Any]],
) -> None:
    name, generated = _a_non_unique_lp(fixtures)
    doc = _copy(cases[name.removesuffix(".json")])
    doc["expected"]["metrics"]["expected_payout"] *= 1.001
    assert any("expected_payout" in d for d in exporter.compare_case(doc, generated))


def test_compare_case_rejects_a_broken_budget(
    fixtures: Any,  # noqa: ANN401
    cases: dict[str, dict[str, Any]],
) -> None:
    name = "step-mse-pure-event-joint-s2.json"
    generated = fixtures.cases[name]
    doc = _copy(cases[name.removesuffix(".json")])
    for levels in doc["expected"]["parameters"].values():
        for key in levels:
            levels[key] *= 1.01
    assert any("budget" in d for d in exporter.compare_case(doc, generated))


def test_compare_documents_finds_a_drift(cases: dict[str, dict[str, Any]]) -> None:
    doc = cases["linear-fixed-pure-annual-individual-h1"]
    other = _copy(doc)
    other["expected"]["premium"]["u1"] *= 1.0 + 1e-6
    assert exporter.compare_documents(doc, other, 1800.0)


def test_compare_documents_accepts_either_atom() -> None:
    either = {"x": {"either": [1.0, 2.0]}}
    assert exporter.compare_documents(either, {"x": 1.0}, 1.0) == []
    assert exporter.compare_documents(either, {"x": 2.0}, 1.0) == []
    assert exporter.compare_documents(either, {"x": 3.0}, 1.0) != []


# --------------------------------------------------------------------------
# The files
# --------------------------------------------------------------------------


def test_files_are_canonical_text() -> None:
    for path in [*CASES_DIR.glob("*.json"), *SAMPLES_DIR.glob("*.json")]:
        text = path.read_text(encoding="utf-8")
        assert text == exporter.render(json.loads(text)), path.name


def test_the_whole_set_is_under_the_size_limit() -> None:
    """ADR 0006 §12: petals accepts only small test files."""
    files = [p for p in SET_DIR.rglob("*") if p.is_file()]
    assert README in files
    assert sum(p.stat().st_size for p in files) <= MAX_TOTAL_BYTES


def test_case_matrix(cases: dict[str, dict[str, Any]]) -> None:
    assert set(cases) == EXPECTED_CASES
    for name, doc in cases.items():
        assert doc["case_id"] == name
        assert doc["source"] == ("core" if name in CORE_CASES else "closed_form"), name


def test_core_cases_are_the_step_matrix(cases: dict[str, dict[str, Any]]) -> None:
    for name in CORE_CASES:
        doc = cases[name]
        assert doc["kind"] == "design"
        payout = doc["cover"]["payout"]
        assert payout["kind"] == "step"
        assert payout["tail"] == "upper"
        assert len(payout["breakpoints"]) == len(payout["levels"])
    objectives = {cases[n]["objective"]["kind"] for n in CORE_CASES}
    assert objectives == {"mse", "expected_uncovered", "weighted_cvar"}
    assert {cases[n]["scope"] for n in CORE_CASES} == {"individual", "joint"}
    assert {cases[n]["basis"]["kind"] for n in CORE_CASES} == {"annual", "event"}
    assert {cases[n]["pricing"]["kind"] for n in CORE_CASES} == {
        "pure",
        "cost_of_capital",
    }


def test_every_document_has_the_contract_fields(
    cases: dict[str, dict[str, Any]], samples: dict[str, dict[str, Any]]
) -> None:
    for name, doc in cases.items():
        assert set(doc) == CASE_FIELDS, name
        assert set(doc["expected"]) == EXPECTED_FIELDS, name
    assert set(samples) == EXPECTED_SAMPLES
    for name, doc in samples.items():
        assert set(doc) == SAMPLE_FIELDS, name
        n, m = len(doc["event_id"]), len(doc["unit_id"])
        assert np.asarray(doc["index"]).shape == (n, m), name
        assert np.asarray(doc["loss"]).shape == (n, m), name
        assert len(doc["frequency"]) == n, name
        assert len(set(doc["event_id"])) == n, name
        assert doc["parent"] is None, name
        assert doc["year"] is None or len(doc["year"]) == n, name


def test_every_case_names_a_shared_sample(
    cases: dict[str, dict[str, Any]], samples: dict[str, dict[str, Any]]
) -> None:
    used: dict[str, int] = {}
    for doc in cases.values():
        match = re.fullmatch(r"samples/([a-z0-9]+)\.json", doc["sample"])
        assert match is not None, doc["case_id"]
        assert match[1] in samples, doc["case_id"]
        assert doc["case_id"].endswith(f"-{match[1]}"), doc["case_id"]
        used[match[1]] = used.get(match[1], 0) + 1
    assert set(used) == set(samples)


def test_the_core_is_only_used_where_it_defines_the_event_basis(
    cases: dict[str, dict[str, Any]], samples: dict[str, dict[str, Any]]
) -> None:
    """ADR 0006 §12: Σf ≤ 1 from the core, Σf above 1 in closed form only."""
    above_one = 0
    for doc in cases.values():
        if doc["basis"]["kind"] != "event":
            continue
        total = math.fsum(_sample_of(doc, samples)["frequency"])
        if doc["source"] == "core":
            assert total <= 1.0, doc["case_id"]
        above_one += total > 1.0
    assert above_one >= 8


def test_annual_cases_have_frequencies_of_one_over_n(
    cases: dict[str, dict[str, Any]], samples: dict[str, dict[str, Any]]
) -> None:
    for doc in cases.values():
        if doc["basis"]["kind"] != "annual":
            continue
        assert doc["basis"]["route"] == "catalogue"
        n_years = doc["basis"]["n_years"]
        sample = _sample_of(doc, samples)
        assert sample["year"] is not None
        assert all(0 <= y < n_years for y in sample["year"]), doc["case_id"]
        assert all(math.isclose(f, 1.0 / n_years) for f in sample["frequency"])


def test_the_tolerance_is_stated_once(cases: dict[str, dict[str, Any]]) -> None:
    assert exporter.TOLERANCE == TOLERANCE
    for doc in cases.values():
        assert set(doc["tolerances"].values()) == {TOLERANCE}, doc["case_id"]
        assert set(doc["tolerances"]) == {
            "objective_value",
            "premium",
            "metrics",
            "parameters",
        }


def test_generator_uses_the_core_alone() -> None:
    """The set is written from ``parametric_insurance_design`` and no CRC or CLIMADA."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    third_party = roots - set(sys.stdlib_module_names)
    assert third_party == {"cvxpy", "numpy", "pandas", "parametric_insurance_design"}


def test_generator_names_a_committed_core(
    cases: dict[str, dict[str, Any]],
) -> None:
    for doc in cases.values():
        generator = doc["generator"]
        assert generator["script"] == "parity/scripts/export_climada_fixtures.py"
        assert re.fullmatch(r"[0-9a-f]{40}", generator["commit"]), doc["case_id"]


def test_the_licence_is_recorded(samples: dict[str, dict[str, Any]]) -> None:
    assert {doc["licence"] for doc in samples.values()} == {"CC0-1.0"}
    assert "CC0-1.0" in README.read_text(encoding="utf-8")
    for path in (PARITY_DIR / "README.md", REPO_ROOT / "docs" / "data-sources.md"):
        text = path.read_text(encoding="utf-8")
        lines = [line for line in text.splitlines() if "climada/samples" in line]
        assert any("CC0-1.0" in line or "CC0 1.0" in line for line in lines), path


def test_readme_counts_match_the_files(
    cases: dict[str, dict[str, Any]], samples: dict[str, dict[str, Any]]
) -> None:
    text = README.read_text(encoding="utf-8")
    match = re.search(r"(\d+) cases and (\d+) samples", text)
    assert match is not None
    assert (int(match[1]), int(match[2])) == (len(cases), len(samples))


# --------------------------------------------------------------------------
# A reader without our code: only the rules of parity/climada/README.md
# --------------------------------------------------------------------------


def _is_free(value: object) -> bool:
    return isinstance(value, dict) and set(value) == {"free"}


def _resolved(
    payout: dict[str, Any], parameters: dict[str, float] | None
) -> dict[str, Any]:
    """Return a payout document with its free amounts set from ``parameters``."""
    if parameters is None:
        return payout
    out = dict(payout)
    if payout["kind"] in ("step", "piecewise_linear"):
        out["levels"] = [
            parameters[f"levels[{k}]"] if _is_free(v) else v
            for k, v in enumerate(payout["levels"])
        ]
    elif payout["kind"] == "linear" and _is_free(payout["limit"]):
        out["limit"] = parameters["limit"]
    elif payout["kind"] == "binary" and _is_free(payout["amount"]):
        out["amount"] = parameters["amount"]
    return out


def _amounts_key(payout: dict[str, Any]) -> tuple[str, int]:
    if payout["kind"] in ("step", "piecewise_linear"):
        return "levels", len(payout["levels"])
    return ("limit", 1) if payout["kind"] == "linear" else ("amount", 1)


def _payout(payout: dict[str, Any], x: np.ndarray) -> np.ndarray:
    """ADR 0006 §3: the payout of a resolved cover, per event."""
    sign = 1.0 if payout["tail"] == "upper" else -1.0
    s = sign * x
    kind = payout["kind"]
    if kind == "step":
        edges = sign * np.asarray(payout["breakpoints"], dtype=float)
        levels = np.asarray(payout["levels"], dtype=float)
        k = np.searchsorted(edges, s, side="right") - 1
        return np.where(k < 0, 0.0, levels[np.maximum(k, 0)])
    if kind == "linear":
        a, e = sign * payout["attachment"], sign * payout["exhaustion"]
        return payout["limit"] * np.clip((s - a) / (e - a), 0.0, 1.0)
    if kind == "piecewise_linear":
        knots = sign * np.asarray(payout["knots"], dtype=float)
        levels = np.asarray(payout["levels"], dtype=float)
        return np.where(s < knots[0], 0.0, np.interp(s, knots, levels))
    if kind == "binary":
        return np.where(s >= sign * payout["trigger"], payout["amount"], 0.0)
    raise ValueError(kind)


def _basis(payout: dict[str, Any], x: np.ndarray) -> np.ndarray:
    """Return the basis ``(n_events, n_amounts)``: the payout is linear in it."""
    key, n = _amounts_key(payout)
    columns = []
    for k in range(n):
        unit = dict(payout)
        unit[key] = (
            [float(j == k) for j in range(n)] if n > 1 or key == "levels" else 1.0
        )
        columns.append(_payout(unit, x))
    return np.column_stack(columns)


def _payout_of_unit(
    case: dict[str, Any], unit: str, parameters: dict[str, Any] | None
) -> dict[str, Any]:
    payout = case["cover"]["payout"]
    if "kind" not in payout:
        payout = payout[unit]
    return _resolved(payout, None if parameters is None else parameters[unit])


def _grouping(
    sample: dict[str, Any], basis: dict[str, Any]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return the grouping ``G``, the outcome weights and which outcomes are events."""
    n = len(sample["event_id"])
    frequency = np.asarray(sample["frequency"], dtype=float)
    if basis["kind"] == "event":
        rest = 1.0 - float(frequency.sum())
        if rest > 1e-9:
            group = np.vstack([np.eye(n), np.zeros(n)])
            return group, np.append(frequency, rest), np.append(np.ones(n, bool), False)
        return np.eye(n), frequency, np.ones(n, bool)
    n_years = basis["n_years"]
    group = np.zeros((n_years, n))
    group[np.asarray(sample["year"]), np.arange(n)] = 1.0
    return group, np.full(n_years, 1.0 / n_years), np.ones(n_years, bool)


def _var(x: np.ndarray, p: np.ndarray, beta: float) -> float:
    """§5.1, §7: the smallest x whose exceedance weight is at most 1 - beta."""
    order = np.argsort(x, kind="stable")
    sorted_x, sorted_p = x[order], p[order]
    above = float(sorted_p.sum()) - np.cumsum(sorted_p)
    below_limit = np.flatnonzero(above <= 1.0 - beta + VAR_ROUNDING)
    return float(sorted_x[below_limit[0]])


def _cvar(x: np.ndarray, p: np.ndarray, beta: float) -> float:
    var = _var(x, p, beta)
    return var + float(p @ np.maximum(x - var, 0.0)) / (1.0 - beta)


def _tail_weights(x: np.ndarray, p: np.ndarray, beta: float) -> np.ndarray:
    var = _var(x, p, beta)
    above, at = x > var, x == var
    remaining = (1.0 - beta) - float(p @ above)
    return np.where(above, p, 0.0) + np.where(at, p * remaining / float(p @ at), 0.0)


def _premium(pricing: dict[str, Any], payout: np.ndarray, p: np.ndarray) -> float:
    expected = float(p @ payout)
    if pricing["kind"] == "pure":
        return expected
    rate = pricing["rate"]
    return (1.0 - rate) * expected + rate * _cvar(payout, p, pricing["q"])


def _objective(
    objective: dict[str, Any],
    loss: np.ndarray,
    payout: np.ndarray,
    uncovered: np.ndarray,
    p: np.ndarray,
) -> float:
    if objective["kind"] == "mse":
        return float(p @ (loss - payout) ** 2)
    expected = float(p @ uncovered)
    if objective["kind"] == "expected_uncovered":
        return expected
    alpha, beta = objective["alpha"], objective["beta"]
    return alpha * _cvar(uncovered, p, beta) + (1.0 - alpha) * expected


def _ratio(a: float, b: float) -> float | None:
    return None if b == 0.0 else a / b


def _label(value: float) -> str:
    return f"{value:g}".replace(".", "_")


def _metrics(
    loss: np.ndarray,
    payout: np.ndarray,
    uncovered: np.ndarray,
    p: np.ndarray,
    kept: np.ndarray,
    premium: float,
    *,
    is_event: bool,
) -> dict[str, float | None]:
    """Every metric column of ADR 0006 §7, for the outcomes given."""
    e_loss, e_payout, e_unc = float(p @ loss), float(p @ payout), float(p @ uncovered)
    weight = float(p.sum())
    m: dict[str, float | None] = {
        "expected_loss": e_loss,
        "expected_payout": e_payout,
        "expected_uncovered": e_unc,
        "premium": premium,
        "rmse": math.sqrt(float(p @ (loss - payout) ** 2)),
        "payout_to_loss_ratio": _ratio(e_payout, e_loss),
        "coverage_ratio": None if e_loss == 0.0 else 1.0 - e_unc / e_loss,
        "payout_frequency": float(p @ (payout > 0.0)),
    }
    dev_l, dev_p = loss - e_loss / weight, payout - e_payout / weight
    var_l, var_p = float(p @ dev_l**2), float(p @ dev_p**2)
    m["correlation"] = (
        None
        if var_l <= 0.0 or var_p <= 0.0
        else float(p @ (dev_l * dev_p)) / math.sqrt(var_l * var_p)
    )
    big, paid = loss > 0.0, payout > 0.0
    m["false_negative_rate_l0"] = _ratio(float(p @ (big & ~paid)), float(p @ big))
    m["false_positive_rate_l0"] = _ratio(
        float(p @ (paid & ~big & kept)), float(p @ (~big & kept))
    )
    for beta in (0.9, 0.99):
        b = _label(beta)
        for name, x in (("uncovered", uncovered), ("loss", loss)):
            m[f"var_{name}_b{b}"] = _var(x, p, beta)
            m[f"cvar_{name}_b{b}"] = _cvar(x, p, beta)
        m[f"var_net_loss_b{b}"] = None
        m[f"cvar_net_loss_b{b}"] = None
        if not is_event:
            net = loss - payout + premium
            m[f"var_net_loss_b{b}"] = _var(net, p, beta)
            m[f"cvar_net_loss_b{b}"] = _cvar(net, p, beta)
        m[f"cvar_uncovered_to_loss_b{b}"] = _ratio(
            _cvar(uncovered, p, beta), _cvar(loss, p, beta)
        )
        w = _tail_weights(loss, p, beta)
        m[f"tail_coverage_b{b}"] = _ratio(
            float(w @ (loss - uncovered)), float(w @ loss)
        )
    for t in (2.0, 10.0, 50.0):
        level = 1.0 - 1.0 / t
        label = _label(t)
        for name, x in (("loss", loss), ("payout", payout), ("uncovered", uncovered)):
            m[f"{name}_rp{label}"] = _var(x, p, level)
        m[f"net_loss_rp{label}"] = (
            None if is_event else _var(loss - payout + premium, p, level)
        )
    return m


def _check_value(name: str, got: float | None, want: object, scale: float) -> None:
    """ADR 0006 §12: within the tolerance, relative; `either` atom; null is null."""
    floor = 1e-9 * (1.0 if name.startswith(UNITLESS) else scale)
    if want is None or got is None:
        assert got is None, (name, got, want)
        assert want is None, (name, got, want)
        return
    if isinstance(want, dict):
        assert set(want) == {"either"}, name
        assert any(
            math.isclose(got, atom, rel_tol=TOLERANCE, abs_tol=floor)
            for atom in want["either"]
        ), (name, got, want)
        return
    assert isinstance(want, float | int), (name, want)
    assert math.isclose(got, want, rel_tol=TOLERANCE, abs_tol=floor), (name, got, want)


def _problems(
    case: dict[str, Any], sample: dict[str, Any]
) -> list[tuple[str | None, list[int]]]:
    """Return ``(unit id or None, unit positions)`` per design problem or row."""
    units = list(range(len(sample["unit_id"])))
    if case["scope"] == "joint":
        return [(None, units)]
    return [(sample["unit_id"][j], [j]) for j in units]


def _scale(sample: dict[str, Any]) -> float:
    return max(1.0, float(np.asarray(sample["loss"], dtype=float).sum(axis=1).max()))


def _of_problem(block: Any, unit: str | None) -> Any:  # noqa: ANN401
    """Pick a problem's value of a block: by unit in the individual scope."""
    return block if unit is None else block[unit]


@pytest.mark.parametrize("name", sorted(EXPECTED_CASES))
def test_a_reader_without_our_code_reproduces_the_case(
    name: str,
    cases: dict[str, dict[str, Any]],
    samples: dict[str, dict[str, Any]],
) -> None:
    case = cases[name]
    sample = _sample_of(case, samples)
    expected = case["expected"]
    is_design = case["kind"] == "design"
    is_event = case["basis"]["kind"] == "event"
    index = np.asarray(sample["index"], dtype=float)
    loss_events = np.asarray(sample["loss"], dtype=float)
    group, p, kept = _grouping(sample, case["basis"])
    scale = _scale(sample)
    parameters = expected["parameters"] if is_design else None

    payouts: list[np.ndarray] = []
    for j, unit in enumerate(sample["unit_id"]):
        resolved = _payout_of_unit(case, unit, parameters)
        payouts.append(_payout(resolved, index[:, j]))
    payout_events = np.column_stack(payouts)

    for unit, positions in _problems(case, sample):
        loss_e = loss_events[:, positions].sum(axis=1)
        payout_e = payout_events[:, positions].sum(axis=1)
        loss_o = group @ loss_e
        payout_o = group @ payout_e
        uncovered_o = group @ np.maximum(loss_e - payout_e, 0.0)
        premium = _premium(case["pricing"], payout_o, p)
        _check_value("premium", premium, _of_problem(expected["premium"], unit), scale)
        if is_design:
            value = _objective(case["objective"], loss_o, payout_o, uncovered_o, p)
            mse = case["objective"]["kind"] == "mse"
            floor = 1e-9 * (scale**2 if mse else scale)
            want = _of_problem(expected["objective_value"], unit)
            assert math.isclose(value, want, rel_tol=TOLERANCE, abs_tol=floor), name
            budget = case["budget"]["ratio"] * float(p @ loss_o)
            assert premium <= budget * (1.0 + 1e-6) + 1e-9 * scale, name
        columns = _metrics(
            loss_o, payout_o, uncovered_o, p, kept, premium, is_event=is_event
        )
        listed = _of_problem(expected["metrics"], unit)
        assert listed, name
        for column, value in listed.items():
            _check_value(column, columns[column], value, scale)


def _design_cases(cases: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c in cases.values() if c["kind"] == "design"]


def test_design_parameters_meet_the_constraints(
    cases: dict[str, dict[str, Any]], samples: dict[str, dict[str, Any]]
) -> None:
    """ADR 0006 §3 and §6.3: amounts ≥ 0, monotone, within the largest event loss."""
    for case in _design_cases(cases):
        sample = _sample_of(case, samples)
        loss = np.asarray(sample["loss"], dtype=float)
        tol = 1e-9 * _scale(sample)
        assert case["limit"] == {"rule": "largest_loss"}, case["case_id"]
        for j, unit in enumerate(sample["unit_id"]):
            amounts = np.asarray(
                list(case["expected"]["parameters"][unit].values()), dtype=float
            )
            assert amounts.min() >= -tol, case["case_id"]
            assert amounts.max() <= loss[:, j].max() + tol, case["case_id"]
            payout = case["cover"]["payout"]
            if payout.get("monotone") and amounts.size > 1:
                assert np.diff(amounts).min() >= -tol, case["case_id"]


def test_unidentified_levels_follow_the_fill_rule(
    cases: dict[str, dict[str, Any]], samples: dict[str, dict[str, Any]]
) -> None:
    """ADR 0006 §6.5: no event reaches them, and ``fill="lowest"`` sets them."""
    filled = 0
    for case in _design_cases(cases):
        sample = _sample_of(case, samples)
        index = np.asarray(sample["index"], dtype=float)
        for j, unit in enumerate(sample["unit_id"]):
            template = case["cover"]["payout"]
            basis = _basis(template, index[:, j])
            key, n = _amounts_key(template)
            names = [f"levels[{k}]" for k in range(n)] if key == "levels" else [key]
            unreached = [names[k] for k in range(n) if not basis[:, k].any()]
            assert case["expected"]["unidentified"][unit] == unreached, case["case_id"]
            values = case["expected"]["parameters"][unit]
            for name in unreached:
                k = names.index(name)
                previous = 0.0 if k == 0 else values[names[k - 1]]
                assert values[name] == previous, case["case_id"]
                filled += 1
    assert filled >= 12


def _is_lp(case: dict[str, Any]) -> bool:
    return case["objective"]["kind"] != "mse"


def _lp_optimum(
    case: dict[str, Any],
    sample: dict[str, Any],
    positions: Sequence[int],
) -> float:
    """Solve the design LP of ADR 0006 §5.1 and §6 with scipy's HiGHS.

    Per-event shortfalls u, the outcome sums ``G u``, Rockafellar-Uryasev
    auxiliaries with ``ζ ≥ 0``, the outcome weights in place of probabilities,
    and amounts in ``[0, largest event loss of the unit]``. Losses are divided
    by the problem's largest event loss.
    """
    index = np.asarray(sample["index"], dtype=float)
    loss_events = np.asarray(sample["loss"], dtype=float)
    loss = loss_events[:, positions].sum(axis=1)
    scale = float(loss.max())
    template = case["cover"]["payout"]
    blocks = [_basis(template, index[:, j]) for j in positions]
    basis = np.hstack(blocks)
    caps = np.concatenate(
        [
            np.full(b.shape[1], loss_events[:, j].max() / scale)
            for b, j in zip(blocks, positions, strict=True)
        ]
    )
    group, p, _ = _grouping(sample, case["basis"])
    n_events, n_amounts, n_outcomes = loss.size, basis.shape[1], p.size
    objective, pricing = case["objective"], case["pricing"]
    is_cvar = objective["kind"] == "weighted_cvar"
    is_loaded = pricing["kind"] == "cost_of_capital"
    # theta, u, zeta, v, eta, w.
    size = n_amounts + n_events + 2 + 2 * n_outcomes
    u0 = n_amounts
    zeta = u0 + n_events
    v0 = zeta + 1
    eta = v0 + n_outcomes
    w0 = eta + 1
    rows: list[np.ndarray] = []
    rhs: list[float] = []
    for e in range(n_events):  # u_e >= L_e - B_e theta
        row = np.zeros(size)
        row[:n_amounts] = -basis[e]
        row[u0 + e] = -1.0
        rows.append(row)
        rhs.append(-loss[e] / scale)
    payout_o = group @ basis
    if is_cvar:
        for o in range(n_outcomes):  # v_o >= (G u)_o - zeta
            row = np.zeros(size)
            row[u0 : u0 + n_events] = group[o]
            row[zeta] = -1.0
            row[v0 + o] = -1.0
            rows.append(row)
            rhs.append(0.0)
    premium = np.zeros(size)
    premium[:n_amounts] = p @ payout_o
    if is_loaded:
        rate, q = pricing["rate"], pricing["q"]
        premium[:n_amounts] *= 1.0 - rate
        premium[eta] = rate
        premium[w0 : w0 + n_outcomes] = rate * p / (1.0 - q)
        for o in range(n_outcomes):  # w_o >= pi_o - eta
            row = np.zeros(size)
            row[:n_amounts] = payout_o[o]
            row[eta] = -1.0
            row[w0 + o] = -1.0
            rows.append(row)
            rhs.append(0.0)
    rows.append(premium)
    rhs.append(case["budget"]["ratio"] * float(p @ (group @ loss)) / scale)
    if template.get("monotone"):
        start = 0
        for block in blocks:
            for k in range(block.shape[1] - 1):
                row = np.zeros(size)
                row[start + k], row[start + k + 1] = 1.0, -1.0
                rows.append(row)
                rhs.append(0.0)
            start += block.shape[1]
    cost = np.zeros(size)
    expected_uncovered = p @ group
    if is_cvar:
        alpha, beta = objective["alpha"], objective["beta"]
        cost[u0 : u0 + n_events] = (1.0 - alpha) * expected_uncovered
        cost[zeta] = alpha
        cost[v0 : v0 + n_outcomes] = alpha * p / (1.0 - beta)
    else:
        cost[u0 : u0 + n_events] = expected_uncovered
    bounds = [(0.0, float(caps[k])) for k in range(n_amounts)]
    bounds += [(0.0, None)] * (size - n_amounts)
    done = linprog(
        cost,
        A_ub=np.vstack(rows),
        b_ub=np.asarray(rhs),
        bounds=bounds,
        method="highs",
    )
    assert done.status == 0, (case["case_id"], done.message)
    return float(done.fun) * scale


@pytest.mark.parametrize(
    "name",
    sorted(n for n in EXPECTED_CASES if "-mse-" not in n and "-fixed-" not in n),
)
def test_lp_designs_are_the_optimum_of_the_adrs_lp(
    name: str,
    cases: dict[str, dict[str, Any]],
    samples: dict[str, dict[str, Any]],
) -> None:
    case = cases[name]
    sample = _sample_of(case, samples)
    assert _is_lp(case)
    for unit, positions in _problems(case, sample):
        got = _lp_optimum(case, sample, positions)
        want = _of_problem(case["expected"]["objective_value"], unit)
        assert math.isclose(
            got, want, rel_tol=TOLERANCE, abs_tol=1e-9 * _scale(sample)
        ), (name, unit, got, want)


@pytest.mark.parametrize(
    "name",
    ["binary-mse-pure-annual-individual-h1", "linear-mse-coc-event-individual-h2"],
)
def test_one_amount_mse_designs_are_the_closed_form(
    name: str,
    cases: dict[str, dict[str, Any]],
    samples: dict[str, dict[str, Any]],
) -> None:
    """README: the fit E[bL] / E[b²] over outcomes, clipped to [0, A_max]."""
    case = cases[name]
    sample = _sample_of(case, samples)
    template = case["cover"]["payout"]
    index = np.asarray(sample["index"], dtype=float)[:, 0]
    loss = np.asarray(sample["loss"], dtype=float)[:, 0]
    group, p, _ = _grouping(sample, case["basis"])
    b_e = _basis(template, index)[:, 0]
    b_o, loss_o = group @ b_e, group @ loss
    unit_premium = _premium(case["pricing"], b_o, p)
    bound = min(
        float(loss.max()), case["budget"]["ratio"] * float(p @ loss_o) / unit_premium
    )
    fit = float(p @ (b_o * loss_o)) / float(p @ b_o**2)
    amount = min(max(fit, 0.0), bound)
    key, _ = _amounts_key(template)
    written = case["expected"]["parameters"]["u1"][key]
    assert math.isclose(amount, written, rel_tol=TOLERANCE), name
    assert case["compare_parameters"] == "exact"
