"""Import isolation of the petals prototype (MAR-168).

``src/petals_parametric`` is moved into ``climada_petals``, which cannot
depend on this repository's packages. These tests run in CI's job
``test (climada, pixi)``; ruff's banned-api rule in
``src/petals_parametric/ruff.toml`` (job ``lint``) catches the same imports
as you write them. Checked here:

* **statically**, every import in the package's files, tests included, is
  the standard library, the package itself, or one of the allowed
  third-party packages (CLIMADA, numpy, scipy and pandas; in the tests also
  xarray, which CLIMADA's ``TCTracks`` are made of). cvxpy, the optional
  dependency of the mean squared error, is never imported statically;
* **at run time**, importing the package and calibrating a cover with the
  linear objectives loads neither this repository's packages nor cvxpy;
* the ruff config bans this repository's packages in the prototype.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "petals_parametric"
LIBRARY_ALLOWED = frozenset({"climada", "numpy", "scipy", "pandas"})
TEST_ALLOWED = LIBRARY_ALLOWED | {"xarray"}
OWN_PACKAGES = (
    "parametric_insurance_design",
    "parametric_insurance_design_climada",
    "parametric_insurance_design_crc",
    "parametric_insurance_design_viz",
)


def _imports(path: Path) -> list[tuple[int, str]]:
    """Return ``(line, top-level module)`` of every absolute import in a file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name.split(".")[0]) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module.split(".")[0]))
    return found


def _files() -> list[Path]:
    files = sorted(PACKAGE.rglob("*.py"))
    assert len(files) > 10, f"no prototype files found under {PACKAGE}"
    return files


@pytest.mark.parametrize("path", _files(), ids=lambda p: str(p.relative_to(PACKAGE)))
def test_every_import_is_allowed(path: Path) -> None:
    allowed = (
        TEST_ALLOWED if "test" in path.relative_to(PACKAGE).parts else LIBRARY_ALLOWED
    )
    stdlib = sys.stdlib_module_names
    bad = [
        (line, module)
        for line, module in _imports(path)
        if module not in stdlib
        and module not in allowed
        and module != "petals_parametric"
    ]
    assert not bad, f"{path.name} imports outside the allowed packages: {bad}"


def test_cvxpy_is_only_imported_lazily() -> None:
    text = (PACKAGE / "solvers.py").read_text(encoding="utf-8")
    assert 'importlib.import_module("cvxpy")' in text
    for path in _files():
        assert all(module != "cvxpy" for _, module in _imports(path)), path.name


def test_the_linear_objectives_load_neither_the_core_nor_cvxpy() -> None:
    script = """
import sys
import numpy as np
import scipy.sparse as sp
from climada.engine import Impact
import petals_parametric as pm

index = pm.ParametricIndex(
    values=[[30.0], [60.0]], event_id=[1, 2], event_name=["a", "b"],
    frequency=[0.1, 0.1], event_year=[0, 1], years=range(10), unit_id=["u"],
    coords=[[25.0, -80.0]],
)
loss = np.array([[4.0], [10.0]])
impact = Impact(
    event_id=np.array([1, 2]), event_name=["a", "b"], date=np.ones(2, dtype=int),
    frequency=np.array([0.1, 0.1]), coord_exp=np.array([[25.0, -80.0]]),
    eai_exp=np.array([1.4]), at_event=loss.sum(axis=1), aai_agg=1.4,
    imp_mat=sp.csr_matrix(loss),
)
for objective in (pm.ExpectedUncovered(), pm.WeightedCVaR(alpha=0.5, beta=0.9)):
    pm.calibrate(index, impact, payout=pm.StepPayout(20.0, 70.0, 2),
                 objective=objective, basis="annual", budget=0.5)
loaded = sorted(m for m in sys.modules
                if m == "cvxpy" or m.split(".")[0] in {OWN})
print(loaded)
assert not loaded, loaded
""".replace("{OWN}", repr(set(OWN_PACKAGES)))
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_ruff_bans_this_repositorys_packages_in_the_prototype() -> None:
    config = tomllib.loads((PACKAGE / "ruff.toml").read_text(encoding="utf-8"))
    assert config["extend"] == "../../pyproject.toml"
    assert "TID251" in config["lint"]["extend-select"]
    banned = config["lint"]["flake8-tidy-imports"]["banned-api"]
    assert set(OWN_PACKAGES) <= set(banned)
