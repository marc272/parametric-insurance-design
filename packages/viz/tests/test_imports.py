"""Viz reads the result store and never solves (SPEC §3.1 C6, MAR-110).

Two checks:

* **Static:** no viz module imports the solver, the problem builder, the
  run executor or the sweeps (which call them), cvxpy, or an adapter
  (ADR 0001). Importing core's ``__init__`` loads every core module, so a
  ``sys.modules`` check cannot tell; the source is parsed instead.
* **Runtime:** drawing the whole figure set with the solver and the builder
  replaced by functions that fail proves that neither is called.
"""

from __future__ import annotations

import ast
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import pytest

import parametric_insurance_design.experiment.runner as runner
import parametric_insurance_design.problem as problem
import parametric_insurance_design.solve as solve
from parametric_insurance_design_viz.command import write_figures

if TYPE_CHECKING:
    from conftest import Fixture

FORBIDDEN_MODULES = (
    "cvxpy",
    "parametric_insurance_design.problem",
    "parametric_insurance_design.solve",
    "parametric_insurance_design.experiment.runner",
    "parametric_insurance_design.experiment.sweeps",
    "parametric_insurance_design.cli",
    "parametric_insurance_design_crc",
    "parametric_insurance_design_climada",
)
FORBIDDEN_NAMES = {  # `from <package> import <name>` forms
    "parametric_insurance_design": {"problem", "solve", "cli"},
    "parametric_insurance_design.experiment": {"runner", "sweeps"},
}
FORBIDDEN_ATTRIBUTES = {"problem", "solve", "runner", "sweeps", "build_problems"}


def viz_sources() -> list[Path]:
    root = Path(str(files("parametric_insurance_design_viz")))
    sources = sorted(root.rglob("*.py"))
    assert sources, root
    return sources


def forbidden(module: str) -> bool:
    return any(module == m or module.startswith(f"{m}.") for m in FORBIDDEN_MODULES)


def violations(source: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if forbidden(a.name)]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if forbidden(node.module):
                found.append(node.module)
            names = FORBIDDEN_NAMES.get(node.module, set())
            found += [f"{node.module}.{a.name}" for a in node.names if a.name in names]
        elif (
            isinstance(node, ast.Attribute)
            and node.attr in FORBIDDEN_ATTRIBUTES
            and isinstance(node.value, ast.Name)
            and node.value.id in {"pid", "parametric_insurance_design"}
        ):
            found.append(f"{node.value.id}.{node.attr}")
        elif isinstance(node, ast.Call):
            func = node.func
            target = func.attr if isinstance(func, ast.Attribute) else ""
            if target in {"import_module", "__import__"} or (
                isinstance(func, ast.Name) and func.id == "__import__"
            ):
                found.append("dynamic import")
    return found


@pytest.mark.parametrize("path", viz_sources(), ids=lambda p: p.name)
def test_no_viz_module_imports_the_solver_or_builder(path: Path) -> None:
    assert violations(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    "source",
    [
        "import cvxpy as cp",
        "from parametric_insurance_design.problem import build_problems",
        "from parametric_insurance_design import solve",
        "import parametric_insurance_design.experiment.runner",
        "from parametric_insurance_design.experiment import sweeps",
        "import parametric_insurance_design_crc",
        "import parametric_insurance_design as pid\npid.solve.solve(x)",
        "importlib.import_module('parametric_insurance_design.solve')",
    ],
)
def test_the_check_catches_forbidden_imports(source: str) -> None:
    assert violations(source)


def test_figures_never_solve(
    toy: Fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("viz must not build or solve a design problem")

    monkeypatch.setattr(problem, "build_problems", refuse)
    monkeypatch.setattr(problem, "build_context", refuse)
    monkeypatch.setattr(solve, "solve", refuse)
    monkeypatch.setattr(runner, "build_problems", refuse)
    monkeypatch.setattr(runner, "solve", refuse)
    monkeypatch.setattr(runner, "execute", refuse)
    report = write_figures(
        toy.config,
        toy.run_ids,
        store=toy.store,
        out_dir=tmp_path,
        eventset=toy.eventset,
    )
    assert report.ok
    # every figure set drew something; per-set contents are tested elsewhere
    names = {w.name for w in report.written}
    assert {"payout_grid_individual", "premium_reallocation"} <= names
