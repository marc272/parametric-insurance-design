"""Tests for the CRC module's golden fixtures, ``parity/crc/cases/`` (MAR-245, MAR-255).

Three groups:

- **Regeneration.** ``parity/scripts/export_crc_fixtures.py`` rebuilds every
  case in memory from the core, and the committed files must pass
  ``compare_case`` against it. Inputs and unique designs are compared with
  the regeneration tolerances. A non-unique design is judged by what holds
  for every point of its optimal set: the committed values are the core's at
  the committed levels, and those levels are feasible, optimal and within the
  ranges of the regenerated problem. So the fixtures cannot drift silently
  from the core, the data or the script, and a solver that returns another
  point of the same optimal set (another platform) does not fail the check.
  A regeneration with perturbed solvers checks the latter here.
- **The files.** Canonical text, under 1 MB in total, the case matrix of
  MAR-245 and MAR-255, at most one draw per year, the holdout blocks, the
  fill rule of unidentified levels, and a generator block that names a
  committed core.
- **A reader without our code.** Each case is read with plain numpy and the
  rules of ``parity/crc/README.md`` only (no core, no script): the payouts of
  the written cover, the objective value, the premium, the budget and the
  plain metrics are recomputed, in sample and out of sample, and must match
  the expected values within the case's tolerances. This is what the
  module's tests in the fork do.
"""

from __future__ import annotations

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

PARITY_DIR = Path(__file__).resolve().parents[1]
SCRIPT = PARITY_DIR / "scripts" / "export_crc_fixtures.py"
CASES_DIR = PARITY_DIR / "crc" / "cases"
MAX_TOTAL_BYTES = 1_000_000

# The case matrix of MAR-245 and MAR-255, stated here independently of the
# script.
OBJECTIVES = ("mse", "eu", "wcvar-b0_9", "wcvar-b0_99")
HOLDOUT_OBJECTIVES = ("mse", "wcvar-b0_9")
PRICINGS = ("pure", "coc")
SCOPES = ("individual", "joint")
DATA = ("synthetic", "thesis")
CLOSED_FORM_FAMILIES = ("linear", "binary", "piecewise-linear")
EXPECTED_CASES = {
    *(
        f"step-{o}-{p}-{s}-{d}"
        for o in OBJECTIVES
        for p in PRICINGS
        for s in SCOPES
        for d in DATA
    ),
    *(f"step-fixed-{p}-individual-{d}" for p in PRICINGS for d in DATA),
    *(
        f"step-{o}-{p}-individual-{d}-holdout"
        for o in HOLDOUT_OBJECTIVES
        for p in PRICINGS
        for d in DATA
    ),
    *(
        f"{f}-upper-fixed-{p}-individual-handmade"
        for f in CLOSED_FORM_FAMILIES
        for p in PRICINGS
    ),
    *(f"{f}-lower-fixed-pure-individual-handmade" for f in CLOSED_FORM_FAMILIES),
    *(f"{f}-upper-fixed-pure-individual-synthetic" for f in CLOSED_FORM_FAMILIES),
    "piecewise-linear-upper-fixed-coc-individual-synthetic",
}
TRAIN_FRACTION = 0.7


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("export_crc_fixtures", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses need the module registered
    spec.loader.exec_module(module)
    return module


exporter = _load_script()


def _committed() -> dict[str, str]:
    return {
        p.name: p.read_text(encoding="utf-8") for p in sorted(CASES_DIR.glob("*.json"))
    }


@pytest.fixture(scope="module")
def generated() -> dict[str, Any]:
    return exporter.build_cases()


@pytest.fixture(scope="module")
def regenerated(generated: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {name: case.document for name, case in generated.items()}


# Another platform's solvers can return another point of a set of optimal
# designs. The local proxy: Clarabel without equilibration (another interior
# path) and HiGHS's primal simplex (another vertex), both still accurate.
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


@pytest.fixture(scope="module")
def cases() -> dict[str, dict[str, Any]]:
    return {name: json.loads(text) for name, text in _committed().items()}


# --------------------------------------------------------------------------
# Regeneration
# --------------------------------------------------------------------------


def test_regeneration_matches_the_committed_cases(
    generated: dict[str, Any], cases: dict[str, dict[str, Any]]
) -> None:
    assert sorted(generated) == sorted(cases), "regenerate: see parity/crc/README.md"
    problems: list[str] = []
    for name, case in generated.items():
        problems += [f"{name}: {p}" for p in exporter.compare_case(cases[name], case)]
    assert not problems, "\n".join(problems[:50])


def test_regeneration_check_holds_with_other_solver_points(
    cases: dict[str, dict[str, Any]],
) -> None:
    perturbed = exporter.build_cases(commit="x", settings=PERTURBED)
    problems: list[str] = []
    moved = []
    for name, case in perturbed.items():
        problems += [f"{name}: {p}" for p in exporter.compare_case(cases[name], case)]
        if exporter.compare_documents(cases[name], case.document):
            moved.append(name)
    assert not problems, "\n".join(problems[:50])
    # The perturbation is real: the raw solver points of non-unique designs
    # moved. (Unidentified levels no longer move: they follow the fill rule.)
    assert "step-wcvar-b0_9-pure-joint-synthetic.json" in moved
    assert "step-eu-pure-joint-thesis.json" in moved
    assert len(moved) >= 6


def _design(cases: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
    return json.loads(json.dumps(cases[name]))


def test_compare_case_rejects_levels_outside_the_optimal_set(
    generated: dict[str, Any], cases: dict[str, dict[str, Any]]
) -> None:
    name = "step-wcvar-b0_9-pure-joint-synthetic.json"
    assert cases[name]["compare_parameters"] == "within_ranges"
    assert exporter.compare_case(cases[name], generated[name]) == []
    doc = _design(cases, name)
    for asset in doc["expected"]["parameters"].values():
        for key in asset:
            asset[key] *= 0.9
    found = exporter.compare_case(doc, generated[name])
    assert any("objective" in p for p in found)
    assert any("outside the range" in p for p in found)
    assert any(p.startswith("expected/metrics") for p in found)


def test_compare_case_rejects_values_that_are_not_the_cores(
    generated: dict[str, Any], cases: dict[str, dict[str, Any]]
) -> None:
    name = "step-mse-coc-joint-thesis.json"
    assert cases[name]["compare_parameters"] == "none"
    doc = _design(cases, name)
    doc["expected"]["metrics"]["rmse"] *= 1 + 1e-9
    doc["expected"]["premium"] *= 1 + 1e-9
    found = exporter.compare_case(doc, generated[name])
    assert any(p.startswith("expected/metrics/rmse") for p in found)
    assert any(p.startswith("expected/premium") for p in found)


def test_compare_case_rejects_a_broken_budget(
    generated: dict[str, Any], cases: dict[str, dict[str, Any]]
) -> None:
    name = "step-eu-coc-joint-thesis.json"
    doc = _design(cases, name)
    for asset in doc["expected"]["parameters"].values():
        for key in asset:
            asset[key] *= 1.5
    found = exporter.compare_case(doc, generated[name])
    assert any("above the budget" in p or "cap" in p for p in found)


def test_compare_case_rejects_out_of_sample_values_that_are_not_the_cores(
    generated: dict[str, Any], cases: dict[str, dict[str, Any]]
) -> None:
    name = "step-wcvar-b0_9-coc-individual-thesis-holdout.json"
    assert exporter.compare_case(cases[name], generated[name]) == []
    doc = _design(cases, name)
    doc["expected"]["out_of_sample"]["metrics"]["cvar_net_loss_b0_9"] *= 1 + 1e-9
    found = exporter.compare_case(doc, generated[name])
    assert any(
        p.startswith("expected/out_of_sample/metrics/cvar_net_loss") for p in found
    )
    # An unidentified level is not compared in sample, but a held-out draw
    # falls into its bin, so another value changes the out-of-sample metrics.
    doc = _design(cases, name)
    assert "levels[4]" in doc["expected"]["unidentified"]
    doc["expected"]["parameters"]["levels[4]"] *= 0.5
    found = exporter.compare_case(doc, generated[name])
    assert any(p.startswith("expected/out_of_sample/metrics") for p in found)


def test_out_of_sample_cases_use_the_design_premium(
    cases: dict[str, dict[str, Any]],
) -> None:
    """Re-pricing on the held-out block (the core's ``kpis``) gives other values."""
    for name, doc in cases.items():
        if doc["split"] is None:
            continue
        e = doc["expected"]
        p, L, pi = _draws(doc["evaluation_sample"], [doc["cover"]], [e["parameters"]])
        repriced = _premium(doc["pricing"], pi, p)
        assert not math.isclose(repriced, e["premium"], rel_tol=1e-3), name
        net = _reader_metrics(L, pi, p, repriced)["cvar_net_loss_b0_9"]
        want = e["out_of_sample"]["metrics"]["cvar_net_loss_b0_9"]
        assert not math.isclose(net, want, rel_tol=1e-3), name


def test_regeneration_is_byte_stable_on_one_machine(
    regenerated: dict[str, dict[str, Any]],
) -> None:
    again = exporter.build_documents(commit="x")
    first = {
        name: exporter.render({**doc, "generator": {**doc["generator"], "commit": "x"}})
        for name, doc in regenerated.items()
    }
    assert {name: exporter.render(doc) for name, doc in again.items()} == first


def test_compare_documents_finds_a_drift(cases: dict[str, dict[str, Any]]) -> None:
    name = "step-eu-pure-individual-synthetic.json"
    doc = json.loads(json.dumps(cases[name]))
    assert exporter.compare_documents(cases[name], doc) == []
    doc["expected"]["objective_value"] *= 1 + 1e-4
    doc["sample"]["loss"][3][0] += 1.0
    doc["compare_parameters"] = "none"
    found = exporter.compare_documents(cases[name], doc)
    assert any(p.startswith("expected/objective_value") for p in found)
    assert any(p.startswith("sample/loss/3/0") for p in found)
    assert any(p.startswith("compare_parameters") for p in found)


def test_compare_documents_accepts_either_atom() -> None:
    sample = {"loss": [[10.0]]}
    a = {"kind": "evaluate", "sample": sample, "expected": {"metrics": {"v": 3.0}}}
    b = {
        "kind": "evaluate",
        "sample": sample,
        "expected": {"metrics": {"v": {"either": [2.0, 3.0]}}},
    }
    assert exporter.compare_documents(a, b) == []
    c = {**a, "expected": {"metrics": {"v": 4.0}}}
    assert exporter.compare_documents(c, b) != []


# --------------------------------------------------------------------------
# The files
# --------------------------------------------------------------------------


def test_files_are_canonical_text() -> None:
    for name, text in _committed().items():
        assert exporter.render(json.loads(text)) == text, name


def test_total_size_is_under_1_mb() -> None:
    total = sum(len(t.encode("utf-8")) for t in _committed().values())
    assert 0 < total < MAX_TOTAL_BYTES


def test_case_matrix(cases: dict[str, dict[str, Any]]) -> None:
    ids = {doc["case_id"] for doc in cases.values()}
    assert ids == EXPECTED_CASES
    for name, doc in cases.items():
        assert name == f"{doc['case_id']}.json"


def test_every_document_has_the_contract_fields(
    cases: dict[str, dict[str, Any]],
) -> None:
    top = {
        "case_id",
        "kind",
        "source",
        "sample",
        "split",
        "evaluation_sample",
        "cover",
        "objective",
        "pricing",
        "budget",
        "limit",
        "scope",
        "expected",
        "compare_parameters",
        "tolerances",
        "generator",
    }
    expected = {
        "objective_value",
        "premium",
        "parameters",
        "unidentified",
        "unique",
        "metrics",
        "out_of_sample",
    }
    for name, doc in cases.items():
        assert set(doc) == top, name
        assert set(doc["expected"]) == expected, name
        assert set(doc["tolerances"]) == {
            "objective_value",
            "premium",
            "metrics",
            "parameters",
        }
        assert set(doc["generator"]) == {"script", "core_version", "commit"}
        assert doc["kind"] in ("design", "evaluate")
        assert doc["source"] in ("core", "closed_form")
        assert doc["scope"] in ("individual", "joint")
        assert doc["compare_parameters"] in ("exact", "within_ranges", "none")
        if doc["kind"] == "evaluate":
            assert doc["compare_parameters"] == "none"
        holdout = name.endswith("-holdout.json")
        if holdout:
            assert doc["kind"] == "design", name
            split = {"kind": "holdout", "train_fraction": TRAIN_FRACTION}
            assert doc["split"] == split, name
            assert doc["evaluation_sample"] is not None, name
            oos = doc["expected"]["out_of_sample"]
            assert set(oos) == {"fold", "premium_basis", "metrics"}, name
            assert oos["fold"] == 0, name
            assert oos["premium_basis"] == "design", name
        else:
            assert doc["split"] is None, name
            assert doc["evaluation_sample"] is None, name
            assert doc["expected"]["out_of_sample"] is None, name


def test_holdout_blocks_partition_the_years(cases: dict[str, dict[str, Any]]) -> None:
    """The design and evaluation samples are the core's holdout of the draws.

    The first ``floor(0.7 * n)`` draws in period order design, the rest
    evaluate (the core's ``splits.holdout``); each block's draws are equally
    likely.
    """
    found = 0
    for name, doc in cases.items():
        if doc["split"] is None:
            continue
        found += 1
        train, test = doc["sample"], doc["evaluation_sample"]
        assert train["asset_ids"] == test["asset_ids"], name
        assert train["index_unit"] == test["index_unit"], name
        assert train["loss_unit"] == test["loss_unit"], name
        period = [*train["period"], *test["period"]]
        assert np.all(np.diff(period) > 0), name
        n = len(period)
        n_train = math.floor(doc["split"]["train_fraction"] * n + 1e-9)
        assert len(train["period"]) == n_train, name
        for block in (train, test):
            k = len(block["period"])
            assert block["probability"] == [1.0 / k] * k, name
    assert found == 8


def test_unidentified_levels_follow_the_fill_rule(
    cases: dict[str, dict[str, Any]],
) -> None:
    """ADR 0005 §5.4, ``fill="lowest"``: the previous identified level, or 0."""
    filled = 0
    for name, doc in cases.items():
        if doc["kind"] != "design":
            continue
        e = doc["expected"]
        if doc["scope"] == "joint":
            rows = [
                (e["parameters"][a], e["unidentified"][a])
                for a in doc["sample"]["asset_ids"]
            ]
        else:
            rows = [(e["parameters"], e["unidentified"])]
        for params, unidentified in rows:
            previous = 0.0
            for k in range(len(params)):
                key = f"levels[{k}]"
                if key in unidentified:
                    assert params[key] == previous, (name, key)
                    filled += 1
                else:
                    previous = params[key]
    assert filled > 0


def test_generator_names_a_committed_core(cases: dict[str, dict[str, Any]]) -> None:
    for name, doc in cases.items():
        assert re.fullmatch(r"[0-9a-f]{40}", doc["generator"]["commit"]), name
        assert doc["generator"]["script"] == "parity/scripts/export_crc_fixtures.py"


def test_samples_have_one_draw_per_year(cases: dict[str, dict[str, Any]]) -> None:
    for name, doc in cases.items():
        for s in (doc["sample"], doc["evaluation_sample"]):
            if s is None:
                continue
            period = np.asarray(s["period"])
            n, m = len(period), len(s["asset_ids"])
            assert np.all(np.diff(period) > 0), name
            assert math.isclose(math.fsum(s["probability"]), 1.0, abs_tol=1e-12), name
            assert np.asarray(s["index"]).shape == (n, m), name
            assert np.asarray(s["loss"]).shape == (n, m), name
            assert np.all(np.asarray(s["loss"]) >= 0), name
            assert (m == 1) == (doc["scope"] == "individual"), name


# --------------------------------------------------------------------------
# A reader without our code (parity/crc/README.md)
# --------------------------------------------------------------------------


def _severity(x: np.ndarray, tail: str) -> np.ndarray:
    return x if tail == "upper" else -x


def _payout(
    cover: dict[str, Any], x: np.ndarray, params: dict[str, float] | None
) -> np.ndarray:
    pay = cover["payout"]
    tail = pay["tail"]
    s = _severity(x, tail)
    if pay["kind"] == "step":
        b = _severity(np.asarray(pay["breakpoints"], dtype=float), tail)
        levels = np.asarray(
            [
                params[f"levels[{k}]"] if params is not None else value
                for k, value in enumerate(pay["levels"])
            ],
            dtype=float,
        )
        k = np.searchsorted(b, s, side="right") - 1
        return np.where(k < 0, 0.0, levels[np.maximum(k, 0)])
    if pay["kind"] == "linear":
        a = _severity(np.asarray(pay["attachment"]), tail)
        e = _severity(np.asarray(pay["exhaustion"]), tail)
        return pay["limit"] * np.clip((s - a) / (e - a), 0.0, 1.0)
    if pay["kind"] == "binary":
        t = _severity(np.asarray(pay["trigger"]), tail)
        return np.where(s >= t, float(pay["amount"]), 0.0)
    if pay["kind"] == "piecewise_linear":
        c = _severity(np.asarray(pay["knots"], dtype=float), tail)
        y = np.asarray(pay["levels"], dtype=float)
        assert np.all(np.diff(c) > 0)
        return np.where(s < c[0], 0.0, np.interp(s, c, y))
    raise AssertionError(f"unknown payout kind {pay['kind']}")


def _var(x: np.ndarray, p: np.ndarray, beta: float) -> float:
    order = np.argsort(x, kind="stable")
    cdf = np.cumsum(p[order])
    return float(x[order][min(int(np.searchsorted(cdf, beta - 1e-10)), x.size - 1)])


def _cvar(x: np.ndarray, p: np.ndarray, beta: float) -> float:
    var = _var(x, p, beta)
    return var + float(p @ np.maximum(x - var, 0.0)) / (1.0 - beta)


def _tail_weights(L: np.ndarray, p: np.ndarray, beta: float) -> np.ndarray:
    """ADR 0005 §6's CVaR_beta weights of the loss; they sum to 1 - beta."""
    var = _var(L, p, beta)
    above, at = L > var, L == var
    w = np.where(above, p, 0.0)
    remaining = (1.0 - beta) - float(p @ above)
    return w + np.where(at, p * remaining / float(p @ at), 0.0)


def _premium(pricing: dict[str, Any], pi: np.ndarray, p: np.ndarray) -> float:
    if pricing["kind"] == "pure":
        return float(p @ pi)
    r, q = pricing["rate"], pricing["q"]
    return (1 - r) * float(p @ pi) + r * _cvar(pi, p, q)


def _label(value: float) -> str:
    text = f"{value:f}".rstrip("0").rstrip(".") if "." in f"{value:f}" else f"{value}"
    return text.replace(".", "_")


def _reader_metrics(
    L: np.ndarray, pi: np.ndarray, p: np.ndarray, premium: float
) -> dict:
    U = np.maximum(L - pi, 0.0)
    N = L - pi + premium
    m: dict[str, float] = {
        "expected_loss": float(p @ L),
        "expected_payout": float(p @ pi),
        "expected_uncovered": float(p @ U),
        "premium": premium,
        "rmse": math.sqrt(float(p @ (L - pi) ** 2)),
        "payout_to_loss_ratio": float(p @ pi) / float(p @ L),
        "coverage_ratio": 1 - float(p @ U) / float(p @ L),
    }
    for beta in (0.9, 0.95, 0.99):
        b = _label(beta)
        for name, x in (("uncovered", U), ("loss", L), ("net_loss", N)):
            m[f"var_{name}_b{b}"] = _var(x, p, beta)
            m[f"cvar_{name}_b{b}"] = _cvar(x, p, beta)
        m[f"cvar_uncovered_to_loss_b{b}"] = _cvar(U, p, beta) / _cvar(L, p, beta)
        w = _tail_weights(L, p, beta)
        m[f"tail_coverage_b{b}"] = float(w @ np.minimum(pi, L)) / float(w @ L)
    for t in (2, 5, 10, 25, 50, 100, 250):
        for name, x in (("loss", L), ("payout", pi), ("uncovered", U), ("net_loss", N)):
            m[f"{name}_rp{t}"] = _var(x, p, 1 - 1 / t)
    big, paid = L > 0.0, pi > 0.0
    m["false_negative_rate_l0"] = float(p @ (big & ~paid)) / float(p @ big)
    m["false_positive_rate_l0"] = float(p @ (paid & ~big)) / float(p @ ~big)
    return m


def _close(got: float, want: float, rtol: float, floor: float) -> bool:
    return math.isclose(got, want, rel_tol=rtol, abs_tol=1e-9 * floor)


def _check_metric(
    name: str, got: float, want: object, rtol: float, floor: float
) -> None:
    if isinstance(want, dict):
        assert any(_close(got, a, rtol, floor) for a in want["either"]), (
            name,
            got,
            want,
        )
    else:
        assert isinstance(want, float), (name, want)
        assert _close(got, want, rtol, floor), (name, got, want)


UNITLESS = (
    "coverage",
    "payout_to",
    "correlation",
    "tail_coverage",
    "cvar_uncovered_to",
    "false_",
)


def _draws(
    sample: dict[str, Any],
    covers: list[dict[str, Any]],
    per_asset: Sequence[dict[str, float] | None],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Probability, summed loss and summed payout per draw of a sample."""
    p = np.asarray(sample["probability"], dtype=float)
    x = np.asarray(sample["index"], dtype=float)
    loss = np.asarray(sample["loss"], dtype=float)
    pi = sum(
        (_payout(c, x[:, j], per_asset[j]) for j, c in enumerate(covers)),
        start=np.zeros(p.size),
    )
    return p, loss.sum(axis=1), pi


def _check_metrics(
    want: dict[str, Any],
    L: np.ndarray,
    pi: np.ndarray,
    p: np.ndarray,
    premium: float,
    rtol: float,
    scale: float,
) -> int:
    """Recompute the plain metrics and compare them; return how many."""
    m = _reader_metrics(L, pi, p, premium)
    if np.std(L) > 0 and np.std(pi) > 0:
        m["correlation"] = float(np.corrcoef(L, pi)[0, 1])
    checked = 0
    for col, value in want.items():
        if col not in m or value is None:
            continue
        floor = 1.0 if col.startswith(UNITLESS) else scale
        _check_metric(col, m[col], value, rtol, floor)
        checked += 1
    return checked


@pytest.mark.parametrize("name", sorted(f"{c}.json" for c in EXPECTED_CASES))
def test_a_reader_without_our_code_reproduces_the_case(
    name: str, cases: dict[str, dict[str, Any]]
) -> None:
    doc = cases[name]
    s, e, tol = doc["sample"], doc["expected"], doc["tolerances"]
    covers = doc["cover"] if doc["scope"] == "joint" else [doc["cover"]]
    assert [c["asset_id"] for c in covers] == s["asset_ids"]
    if doc["kind"] == "design":
        params = e["parameters"]
        per_asset = (
            [params[a] for a in s["asset_ids"]] if doc["scope"] == "joint" else [params]
        )
    else:
        per_asset = [None] * len(covers)
    p, L, pi = _draws(s, covers, per_asset)
    scale = max(1.0, float(L.max()))
    premium = _premium(doc["pricing"], pi, p)
    assert _close(premium, e["premium"], tol["premium"], scale)
    if doc["kind"] == "design":
        objective = doc["objective"]
        U = np.maximum(L - pi, 0.0)
        if objective["kind"] == "mse":
            value, floor = float(p @ (L - pi) ** 2), scale**2
        elif objective["kind"] == "expected_uncovered":
            value, floor = float(p @ U), scale
        else:
            a, beta = objective["alpha"], objective["beta"]
            value, floor = a * _cvar(U, p, beta) + (1 - a) * float(p @ U), scale
        assert _close(value, e["objective_value"], tol["objective_value"], floor)
        assert premium <= doc["budget"]["ratio"] * float(p @ L) * (1 + tol["premium"])
        for c, theta in zip(covers, per_asset, strict=True):
            assert theta is not None
            levels = np.asarray([theta[f"levels[{k}]"] for k in range(len(theta))])
            uppers = np.asarray([lvl["free"]["upper"] for lvl in c["payout"]["levels"]])
            assert np.all(levels >= 0.0)
            assert np.all(levels <= uppers * (1 + 1e-9))
            assert np.all(np.diff(levels) >= -1e-9 * scale)
    assert _check_metrics(e["metrics"], L, pi, p, premium, tol["metrics"], scale) >= 40
    if doc["split"] is None:
        return
    # Out of sample: the design evaluated on the held-out block, with the
    # design premium (premium_basis "design"), not one priced on that block.
    oos = e["out_of_sample"]
    assert oos["premium_basis"] == "design"
    p_test, L_test, pi_test = _draws(doc["evaluation_sample"], covers, per_asset)
    assert oos["metrics"]["premium"] == e["premium"]
    checked = _check_metrics(
        oos["metrics"], L_test, pi_test, p_test, e["premium"], tol["metrics"], scale
    )
    assert checked >= 40
