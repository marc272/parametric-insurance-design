"""The core never imports an adapter dynamically (ADR 0001, MAR-122).

The BSD-licensed core must never load the GPL/AGPL adapters
(``parametric_insurance_design_crc``, ``parametric_insurance_design_climada``).
Ruff's ``TID251`` (MAR-76) bans their *static* imports only, so this test
parses every core module with :mod:`ast` and checks the dynamic routes:
``importlib.import_module``, ``importlib.__import__`` and ``__import__``,
including names bound by ``from importlib import import_module [as alias]``.

A dynamic import fails the check when

* its module argument is a string literal naming an adapter, or
* its module argument is not a string literal (a name, an f-string, a
  concatenation, ...), unless the call site is allow-listed.

The allow-list holds two call sites, keyed by module and enclosing function:
``parametric_insurance_design.cli._import_viz``, the MAR-110 lazy import of
the viz package for ``figures``, and ``parametric_insurance_design.cli.
_import_export``, the MAR-200 one for ``export-site``. Their arguments are the
module constants ``VIZ_MODULE`` and ``EXPORT_MODULE``, not literals, so each
allow-list entry also pins that argument expression, and
:func:`test_the_allowed_call_site_imports_viz` checks at runtime that the
constants name viz modules (not an adapter) and that the call sites still
exist, so the allow-list cannot go stale.

A runtime check (MAR-123) complements both static ones: a fresh interpreter
imports the core and every one of its submodules (found with
:func:`pkgutil.walk_packages`), then reports which adapter or viz modules are
in :data:`sys.modules`. It sees indirect loads that no source check can, for
example a third-party dependency that imports an adapter. Viz is forbidden
too: the core loads it only when the ``figures`` command runs, so importing
the core must not (this test never calls :func:`cli.main`). A submodule that
fails to import, or writes to stdout or stderr while importing, fails the
check instead of being skipped.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import pytest

from parametric_insurance_design import cli

CORE_PACKAGE = "parametric_insurance_design"
ADAPTER_PACKAGES = (
    "parametric_insurance_design_crc",
    "parametric_insurance_design_climada",
)
VIZ_PACKAGE = "parametric_insurance_design_viz"
NOT_LOADED_BY_CORE = (*ADAPTER_PACKAGES, VIZ_PACKAGE)
"""Packages that importing the core must not load (runtime check)."""
IMPORT_FUNCTIONS = frozenset({"import_module", "__import__"})
"""Function names of the dynamic-import routes, called as ``x.<name>(...)``."""

ALLOWED: dict[tuple[str, str], str] = {
    # (module, enclosing function): the argument expression, as source text
    (f"{CORE_PACKAGE}.cli", "_import_viz"): "VIZ_MODULE",
    (f"{CORE_PACKAGE}.cli", "_import_export"): "EXPORT_MODULE",
}
"""Call sites allowed a non-literal module argument (the lazy viz imports of
``figures``, MAR-110, and ``export-site``, MAR-200)."""


@dataclass(frozen=True)
class DynamicImport:
    """One dynamic-import call found in a module's source."""

    module: str
    function: str  # qualified name of the enclosing function, "" at module level
    line: int
    argument: ast.expr | None

    @property
    def argument_source(self) -> str:
        return "" if self.argument is None else ast.unparse(self.argument)

    def __str__(self) -> str:
        where = f"{self.module}.{self.function}" if self.function else self.module
        return f"{where} (line {self.line}): import of {self.argument_source!r}"


class _Finder(ast.NodeVisitor):
    """Collect dynamic-import calls with their enclosing function."""

    def __init__(self, module: str) -> None:
        self.module = module
        self.scope: list[str] = []
        # bare names that call an import function: the builtin, plus any
        # `from importlib import import_module [as alias]` binding
        self.aliases: set[str] = {"__import__"}
        self.calls: list[DynamicImport] = []

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module in {"importlib", "builtins"}:
            self.aliases |= {
                a.asname or a.name for a in node.names if a.name in IMPORT_FUNCTIONS
            }
        self.generic_visit(node)

    def _visit_scope(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = _visit_scope
    visit_AsyncFunctionDef = _visit_scope

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if (isinstance(func, ast.Attribute) and func.attr in IMPORT_FUNCTIONS) or (
            isinstance(func, ast.Name) and func.id in self.aliases
        ):
            argument = node.args[0] if node.args else None
            for keyword in node.keywords:
                if keyword.arg == "name":
                    argument = keyword.value
            self.calls.append(
                DynamicImport(self.module, ".".join(self.scope), node.lineno, argument)
            )
        self.generic_visit(node)


def dynamic_imports(source: str, module: str) -> list[DynamicImport]:
    finder = _Finder(module)
    finder.visit(ast.parse(source))
    return finder.calls


def names_adapter(name: str) -> bool:
    return any(name == p or name.startswith(f"{p}.") for p in ADAPTER_PACKAGES)


def violations(source: str, module: str = f"{CORE_PACKAGE}.example") -> list[str]:
    found: list[str] = []
    for call in dynamic_imports(source, module):
        argument = call.argument
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            if names_adapter(argument.value):
                found.append(f"adapter import: {call}")
        elif ALLOWED.get((call.module, call.function)) != call.argument_source:
            found.append(f"non-literal import: {call}")
    return found


def core_sources() -> dict[str, Path]:
    """Every core module, keyed by its dotted name."""
    root = Path(str(files(CORE_PACKAGE)))
    sources: dict[str, Path] = {}
    for path in sorted(root.rglob("*.py")):
        parts = path.relative_to(root).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        sources[".".join((CORE_PACKAGE, *parts))] = path
    assert f"{CORE_PACKAGE}.cli" in sources, root
    return sources


@pytest.mark.parametrize(
    ("module", "path"), [pytest.param(m, p, id=m) for m, p in core_sources().items()]
)
def test_no_core_module_imports_an_adapter_dynamically(module: str, path: Path) -> None:
    assert violations(path.read_text(encoding="utf-8"), module) == []


def test_the_allowed_call_site_imports_viz() -> None:
    """The allow-listed site exists, and its argument names viz, not an adapter."""
    sources = core_sources()
    found = {
        (c.module, c.function): c.argument_source
        for module in {m for m, _ in ALLOWED}
        for c in dynamic_imports(sources[module].read_text(encoding="utf-8"), module)
    }
    for site, argument in ALLOWED.items():
        assert found.get(site) == argument, f"allow-listed call site gone: {site}"
    assert cli.VIZ_MODULE == "parametric_insurance_design_viz.command"
    assert not names_adapter(cli.VIZ_MODULE)
    assert cli.EXPORT_MODULE == "parametric_insurance_design_viz.site_export"
    assert not names_adapter(cli.EXPORT_MODULE)


@pytest.mark.parametrize(
    "source",
    [
        "import importlib\nimportlib.import_module('parametric_insurance_design_crc')",
        "import importlib\n"
        "importlib.import_module('parametric_insurance_design_climada.pipeline')",
        "import importlib\n"
        "importlib.__import__('parametric_insurance_design_crc.showcase')",
        "__import__('parametric_insurance_design_climada')",
        "m = __import__(name='parametric_insurance_design_crc')",
        "from importlib import import_module\n"
        "import_module('parametric_insurance_design_crc')",
        "from importlib import import_module as load\n"
        "load('parametric_insurance_design_climada')",
        "import importlib as il\nil.import_module('parametric_insurance_design_crc')",
        "import builtins\nbuiltins.__import__('parametric_insurance_design_crc')",
        # non-literal arguments outside the allow-list
        "import importlib\nNAME = 'x'\nimportlib.import_module(NAME)",
        "import importlib\n"
        "def f(pkg):\n    return importlib.import_module(f'{pkg}.command')",
        "__import__('parametric_insurance_design' + '_crc')",
        "from importlib import import_module as load\nload(VIZ_MODULE)",
        "import importlib\nimportlib.import_module()",
    ],
)
def test_the_check_rejects_dynamic_adapter_imports(source: str) -> None:
    assert violations(source)


def test_the_allow_list_is_keyed_by_module_and_function() -> None:
    call = "import importlib\ndef {f}():\n    return importlib.import_module({a})\n"
    cli_module = f"{CORE_PACKAGE}.cli"
    allowed = call.format(f="_import_viz", a="VIZ_MODULE")
    assert violations(allowed, cli_module) == []
    # the same call in another function, another module, or with another argument
    assert violations(call.format(f="_other", a="VIZ_MODULE"), cli_module)
    assert violations(allowed, f"{CORE_PACKAGE}.solve")
    assert violations(call.format(f="_import_viz", a="ADAPTER"), cli_module)


@pytest.mark.parametrize(
    "source",
    [
        "import importlib\nimportlib.import_module('json')",
        "from importlib.metadata import version\nversion('cvxpy')",
        "import parametric_insurance_design",
    ],
)
def test_the_check_accepts_other_imports(source: str) -> None:
    assert violations(source) == []


# Runtime check (MAR-123) -----------------------------------------------------

PROBE = """
import contextlib, importlib, io, json, pkgutil, sys, traceback

root, package, *forbidden = sys.argv[1:]
if root:
    sys.path.insert(0, root)
output = io.StringIO()
failed = {}

def record(name):
    failed[name] = traceback.format_exc()

with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
    imported = [package]
    try:
        top = importlib.import_module(package)
    except Exception:
        record(package)
    else:
        for info in pkgutil.walk_packages(
            top.__path__, prefix=f"{package}.", onerror=record
        ):
            imported.append(info.name)
            try:
                importlib.import_module(info.name)
            except Exception:
                record(info.name)
loaded = sorted(
    m for m in sys.modules
    if any(m == p or m.startswith(f"{p}.") for p in forbidden)
)
print(json.dumps(
    {"imported": imported, "failed": failed, "output": output.getvalue(),
     "loaded": loaded}
))
"""
"""Run as ``python -I -c PROBE <sys.path root or ""> <package> <forbidden ...>``."""


@dataclass(frozen=True)
class Probe:
    """What a fresh interpreter saw while importing a package tree."""

    imported: list[str]  # the package and every submodule walk_packages found
    failed: dict[str, str]  # module name -> traceback
    output: str  # anything written to stdout or stderr while importing
    loaded: list[str]  # forbidden modules in sys.modules afterwards


def probe(
    package: str,
    forbidden: tuple[str, ...] = NOT_LOADED_BY_CORE,
    root: Path | None = None,
) -> Probe:
    """Import ``package`` and all its submodules in a fresh, isolated interpreter.

    ``-I`` keeps the working directory, ``PYTHONPATH`` and user site-packages
    off ``sys.path``; ``root``, if given, is prepended to it.
    """
    args = [str(root or ""), package, *forbidden]
    result = subprocess.run(
        [sys.executable, "-I", "-c", PROBE, *args],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    return Probe(**json.loads(result.stdout))


def test_importing_the_core_loads_no_adapter_or_viz() -> None:
    seen = probe(CORE_PACKAGE)
    assert seen.failed == {}, "\n".join(seen.failed.values())
    assert seen.output == ""
    assert seen.loaded == []
    # walk_packages found every module the AST check parses, and nothing else
    assert sorted(seen.imported) == sorted(core_sources())


def _fake_tree(root: Path, sources: dict[str, str]) -> Path:
    """Write ``sources`` (relative path -> source) under ``root``."""
    for relative, source in sources.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return root


def test_the_runtime_check_sees_indirect_loads(tmp_path: Path) -> None:
    """A submodule loads an adapter through a third module: the probe sees it."""
    root = _fake_tree(
        tmp_path,
        {
            "fake_core/__init__.py": "",
            "fake_core/clean.py": "import json\n",
            "fake_core/deep/__init__.py": "",
            "fake_core/deep/uses_helper.py": "import helper\n",
            "helper.py": "import importlib\n"
            "importlib.import_module('parametric_insurance_design_crc.x')\n",
            "parametric_insurance_design_crc/__init__.py": "",
            "parametric_insurance_design_crc/x.py": "",
        },
    )
    seen = probe("fake_core", root=root)
    assert seen.failed == {}
    assert seen.output == ""
    assert seen.imported == [
        "fake_core",
        "fake_core.clean",
        "fake_core.deep",
        "fake_core.deep.uses_helper",
    ]
    assert seen.loaded == [
        "parametric_insurance_design_crc",
        "parametric_insurance_design_crc.x",
    ]


def test_the_runtime_check_reports_failures_and_output(tmp_path: Path) -> None:
    """A failing or noisy submodule is reported, never skipped."""
    root = _fake_tree(
        tmp_path,
        {
            "fake_core/__init__.py": "",
            "fake_core/broken.py": "raise RuntimeError('boom')\n",
            "fake_core/broken_pkg/__init__.py": "raise ImportError('gone')\n",
            "fake_core/noisy.py": "import warnings\nprint('side effect')\n"
            "warnings.warn('careful', UserWarning, stacklevel=1)\n",
        },
    )
    seen = probe("fake_core", root=root)
    assert sorted(seen.failed) == ["fake_core.broken", "fake_core.broken_pkg"]
    assert "boom" in seen.failed["fake_core.broken"]
    assert "gone" in seen.failed["fake_core.broken_pkg"]
    assert "side effect" in seen.output
    assert "careful" in seen.output
    assert seen.loaded == []
