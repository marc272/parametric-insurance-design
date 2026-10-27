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

The allow-list holds one call site, keyed by module and enclosing function:
``parametric_insurance_design.cli._import_viz``, the MAR-110 lazy import of
the viz package. Its argument is the module constant ``VIZ_MODULE``, not a
literal, so the allow-list entry also pins that argument expression, and
:func:`test_the_allowed_call_site_imports_viz` checks at runtime that the
constant names the viz module (not an adapter) and that the call site still
exists, so the allow-list cannot go stale.
"""

from __future__ import annotations

import ast
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
IMPORT_FUNCTIONS = frozenset({"import_module", "__import__"})
"""Function names of the dynamic-import routes, called as ``x.<name>(...)``."""

ALLOWED: dict[tuple[str, str], str] = {
    # (module, enclosing function): the argument expression, as source text
    (f"{CORE_PACKAGE}.cli", "_import_viz"): "VIZ_MODULE",
}
"""Call sites allowed a non-literal module argument (MAR-110 lazy viz import)."""


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
