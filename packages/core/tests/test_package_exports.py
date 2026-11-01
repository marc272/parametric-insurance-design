"""The curated top level (ADR 0004 Q2, ADR 0002 §1; MAR-61, MAR-153, MAR-184)."""

from __future__ import annotations

import ast
import importlib
import importlib.util
import json
import pkgutil
import subprocess
import sys
from pathlib import Path

import parametric_insurance_design as pid
from parametric_insurance_design import (
    clustering,
    constraints,
    objectives,
    payout,
    pricing,
    scopes,
    workflow,
)

STORY_NAMES = {
    # tail-risk objective
    "MSE": objectives.MSE,
    "ExpectedUncovered": objectives.ExpectedUncovered,
    "WeightedCVaR": objectives.WeightedCVaR,
    # portfolio calibration
    "Individual": scopes.Individual,
    "Portfolio": scopes.Portfolio,
    "Cluster": scopes.Cluster,
    "ThesisWardClustering": clustering.ThesisWardClustering,
    # the rest of a design
    "StepPayout": payout.StepPayout,
    "PurePremium": pricing.PurePremium,
    "CostOfCapitalLoad": pricing.CostOfCapitalLoad,
    "Budget": constraints.Budget,
    # one call
    "design": workflow.design,
}
DATA_CONTRACT = {
    "Basis",
    "DesignProblem",
    "Entity",
    "EventSet",
    "EventSetMetadata",
    "OutcomeMeasure",
    "ParametricInsuranceDesignError",
    "ProblemSpec",
    "Sample",
    "SolveError",
    "SolveResult",
    "SolveStatus",
}
MODULES = {
    "basis",
    "bootstrap",
    "clustering",
    "constraints",
    "errors",
    "evaluate",
    "eventset",
    "index",
    "interfaces",
    "objectives",
    "payout",
    "pricing",
    "problem",
    "records",
    "riskmeasures",
    "scopes",
    "solve",
    "splits",
    "workflow",
}
OFF_THE_TOP_LEVEL = {"noise", "robust"}
"""Library modules ``__init__`` does not import (ADR 0004 Q2, review F10)."""
NOT_LIBRARY_MODULES = {"cli"}
PACKAGE = "parametric_insurance_design"


def test_the_top_level_list_is_pinned() -> None:
    # A change to the public API is a deliberate change of this list.
    expected = set(STORY_NAMES) | DATA_CONTRACT | MODULES | {"__version__"}
    assert set(pid.__all__) == expected
    assert len(pid.__all__) == len(expected)  # no name listed twice


def test_every_listed_name_is_a_package_attribute() -> None:
    for name in pid.__all__:
        assert hasattr(pid, name), name


def test_the_story_names_are_the_module_objects() -> None:
    for name, obj in STORY_NAMES.items():
        assert getattr(pid, name) is obj, name


def test_solve_and_problem_stay_modules() -> None:
    # `pid.solve` is the module, not the function (ADR 0004 Q2, option 2C):
    # the solver functions are not re-exported.
    assert pid.solve is importlib.import_module(f"{PACKAGE}.solve")
    assert pid.problem is importlib.import_module(f"{PACKAGE}.problem")
    assert callable(pid.solve.solve)
    assert pid.solve.DEFAULT_POLICY is not None
    assert "build_problems" not in pid.__all__
    assert not hasattr(pid, "build_problems")


def test_bootstrap_and_riskmeasures_are_package_attributes() -> None:
    # MAR-153: MAR-143 added these modules; they are imported by __init__.
    from parametric_insurance_design import bootstrap, riskmeasures

    assert pid.bootstrap is bootstrap
    assert pid.riskmeasures is riskmeasures
    assert callable(pid.bootstrap.premium_replicates)
    assert callable(pid.riskmeasures.var_cvar)
    assert "bootstrap" in pid.__all__
    assert "riskmeasures" in pid.__all__


def library_modules() -> set[str]:
    """Top-level modules of the core library, without private ones."""
    return {
        m.name
        for m in pkgutil.iter_modules(pid.__path__)
        if not m.ispkg and not m.name.startswith("_")
    }


def test_every_library_module_but_noise_and_robust_is_a_package_attribute() -> None:
    # ADR 0002 §1 (amended by MAR-184): __init__ imports every top-level
    # module except the CLI, `noise` and `robust`, and lists it in __all__.
    names = library_modules()
    assert OFF_THE_TOP_LEVEL | NOT_LIBRARY_MODULES <= names
    assert names - OFF_THE_TOP_LEVEL - NOT_LIBRARY_MODULES == MODULES
    for name in sorted(MODULES):
        module = importlib.import_module(f"{PACKAGE}.{name}")
        assert getattr(pid, name, None) is module, name


def test_noise_and_robust_are_not_listed() -> None:
    assert not OFF_THE_TOP_LEVEL & set(pid.__all__)
    assert "cli" not in pid.__all__
    assert "experiment" not in pid.__all__


FRESH_IMPORT = """
import json, sys
import parametric_insurance_design as pid
print(json.dumps({
    "loaded": sorted(m for m in sys.modules if m.startswith(sys.argv[1])),
    "attributes": sorted(n for n in sys.argv[2:] if hasattr(pid, n)),
}))
"""


def fresh_import(*attributes: str) -> tuple[list[str], list[str]]:
    """Import the package in a fresh interpreter.

    Returns the package's modules then in ``sys.modules``, and which of
    ``attributes`` the package has. Other tests import submodules, which sets
    them as package attributes in this process, so only a fresh interpreter
    tells what ``__init__`` itself imports.
    """
    result = subprocess.run(
        [sys.executable, "-I", "-c", FRESH_IMPORT, f"{PACKAGE}.", *attributes],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    seen = json.loads(result.stdout)
    return seen["loaded"], seen["attributes"]


def test_importing_the_package_imports_neither_noise_nor_robust() -> None:
    loaded, attributes = fresh_import("noise", "robust", "cli", "experiment")
    assert attributes == []
    for name in [*OFF_THE_TOP_LEVEL, *NOT_LIBRARY_MODULES, "experiment"]:
        assert f"{PACKAGE}.{name}" not in loaded, name
    assert {f"{PACKAGE}.{name}" for name in MODULES} <= set(loaded)


def test_noise_and_robust_stay_importable_by_their_full_names() -> None:
    # Only the top-level re-export goes; the modules stay supported.
    noise = importlib.import_module(f"{PACKAGE}.noise")
    robust = importlib.import_module(f"{PACKAGE}.robust")
    assert callable(noise.add_noise)
    assert callable(robust.build_scenario_robust)
    from parametric_insurance_design import noise as noise_again
    from parametric_insurance_design import robust as robust_again

    assert noise_again is noise
    assert robust_again is robust


def core_imports() -> dict[str, set[str]]:
    """Core module (dotted name) -> the core modules it imports, statically."""
    root = Path(pid.__file__).parent
    found: dict[str, set[str]] = {}
    for path in sorted(root.rglob("*.py")):
        parts = (PACKAGE, *path.relative_to(root).with_suffix("").parts)
        is_package = parts[-1] == "__init__"
        name = ".".join(parts[:-1] if is_package else parts)
        package = name if is_package else name.rpartition(".")[0]
        targets: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                targets |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                base = importlib.util.resolve_name(
                    "." * node.level + (node.module or ""), package
                )
                targets.add(base)
                targets |= {f"{base}.{a.name}" for a in node.names}
        found[name] = {t for t in targets if t.startswith(f"{PACKAGE}.")}
    return found


def test_only_the_experiment_layer_imports_noise_and_nothing_imports_robust() -> None:
    # ADR 0004 migration step 3: "only experiment/ imports noise".
    imports = core_imports()
    assert f"{PACKAGE}.workflow" in imports  # the scan sees every module

    def importers(target: str) -> list[str]:
        return sorted(m for m, imported in imports.items() if target in imported)

    assert importers(f"{PACKAGE}.robust") == []
    noise_importers = importers(f"{PACKAGE}.noise")
    assert noise_importers, "the runner applies the noise layer"
    assert all(m.startswith(f"{PACKAGE}.experiment.") for m in noise_importers)
