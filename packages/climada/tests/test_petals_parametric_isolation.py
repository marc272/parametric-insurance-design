"""Import isolation of the petals prototype (MAR-168, MAR-259).

``src/petals_parametric`` is moved into ``climada_petals``, which cannot
depend on this repository's packages. These tests run in CI's job
``test (climada, pixi)``; ruff's banned-api rule in
``src/petals_parametric/ruff.toml`` (job ``lint``) catches the same static
imports as you write them. Checked here:

* **statically**, every import in the package's files, tests included, is
  the standard library, the package itself, or one of the allowed
  third-party packages (CLIMADA, numpy, scipy and pandas; in the tests also
  xarray, which CLIMADA's ``TCTracks`` are made of). cvxpy, the optional
  dependency of the mean squared error, is never imported statically;
* **dynamically** (MAR-259), no file loads a module by name at run time,
  except at the call sites of :data:`ALLOWED_CALLS`, below;
* **at run time**, importing the package and calibrating a cover with the
  linear objectives loads neither this repository's packages nor cvxpy;
* the ruff config bans this repository's packages in the prototype.

The dynamic-import check
------------------------
TID251 and the static check see ``import`` statements only, and the run-time
check sees only the code it runs, so a dynamic import in a function it never
calls (the metrics, the mean squared error) would pass both. This check
follows the core's ``tests/test_import_boundaries.py`` (MAR-122): it parses
every file of the package, ``test/`` included, with :mod:`ast` and refuses
what it cannot prove safe. A file fails on

1. **an import call** by any route: ``importlib.import_module``,
   ``importlib.__import__``, the builtin ``__import__`` or
   ``builtins.__import__``, through a module alias (``import importlib as
   il``), a name bound by ``from importlib import import_module [as x]``, or
   the attribute on any other object (``sys.modules["importlib"]
   .import_module``). Only the sites in :data:`ALLOWED_CALLS` pass, each
   pinned to its file, enclosing function and one positional string literal:
   ``importlib.import_module("cvxpy")`` in ``solvers._import_cvxpy``, and
   ``importlib.util.find_spec("cvxpy")`` at module level of
   ``test/test_calibrate.py`` (``find_spec`` of a top-level name finds the
   module without running it). Any other literal, any non-literal argument
   (a name, an f-string, a concatenation, ``*args``), any keyword and a
   missing argument fail;
2. **the rest of the import machinery**: a static import of one of
   :data:`MACHINERY_MODULES` or of an ``importlib`` submodule other than
   ``importlib.util``; a name from ``importlib`` other than
   ``import_module`` and ``util``, or from ``importlib.util`` other than
   ``find_spec``; any use of ``importlib`` other than an allow-listed call
   (``importlib.reload``, ``importlib.util.spec_from_file_location``,
   ``getattr(importlib, ...)``, handing the module on); a loader attribute
   of :data:`FORBIDDEN_ATTRIBUTES` on any object, or imported by name from
   any module (``exec_module``, ``SourceFileLoader``, ``run_path``,
   ``resolve_name``, ...); and ``sys.modules`` or another of
   :data:`SYS_IMPORT_STATE`;
3. **code execution and the builtins**: a name of :data:`FORBIDDEN_NAMES`
   (``exec``, ``eval``, ``compile``, ``__builtins__``, ``globals``, ...),
   the attributes ``__globals__`` and ``__dict__``, a star import, a
   ``getattr`` whose attribute name is not a string literal, and a name
   bound to two different modules in one file;
4. **strings**: a string or bytes literal outside docstrings (f-string parts
   included) that names one of this repository's packages, which covers
   ``exec`` or ``eval`` of an import string and every API that imports by
   name (``mock.patch``, pickles, entry points); or that equals a name of
   rules 1 to 3 (``getattr(m, "__import__")``, ``globals()["__builtins__"]``);
5. **a ``mock.patch`` target** (``patch``, ``patch.dict``,
   ``patch.multiple``): mock imports it, so it must be a string literal
   whose top-level module the static check allows.

It does not see introspection that names none of these
(``().__class__.__base__.__subclasses__()``), helpers such as
``operator.attrgetter``, or a module name assembled at run time and passed
to a third-party API that imports by name. A dependency's own imports are
the run-time check's job, which sees them on the paths it runs.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path, PurePosixPath

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
OWN_PREFIX = "parametric_insurance_design"
"""Every one of this repository's packages starts with this."""

ALLOWED_CALLS: frozenset[tuple[str, str, str, str]] = frozenset(
    {
        # (file in the package, enclosing function, callee, its one argument)
        ("solvers.py", "_import_cvxpy", "importlib.import_module", "cvxpy"),
        ("test/test_calibrate.py", "", "importlib.util.find_spec", "cvxpy"),
    }
)
"""The only dynamic-import calls the prototype may make."""
ALLOWED_CALLEES = frozenset(callee for _, _, callee, _ in ALLOWED_CALLS)
IMPORTLIB_FROM = {
    "importlib": {"import_module", "util"},
    "importlib.util": {"find_spec"},
}
"""The names ``from importlib[.util] import ...`` may bind."""
MACHINERY_MODULES = frozenset(
    {
        "_frozen_importlib",
        "_frozen_importlib_external",
        "_imp",
        "builtins",
        "code",
        "codeop",
        "imp",
        "pkgutil",
        "pydoc",
        "runpy",
        "zipimport",
    }
)
"""Standard-library modules that load or run code by name; never imported."""
SYS_IMPORT_STATE = ("sys.meta_path", "sys.modules", "sys.path_hooks")
"""``sys`` attributes that hand out loaded modules or the finders."""
FORBIDDEN_ATTRIBUTES = frozenset(
    {
        # import calls, finders and loaders (importlib, importlib.util,
        # importlib.machinery, pkgutil, runpy, pydoc, zipimport)
        "__import__",
        "import_module",
        "reload",
        "find_spec",
        "find_loader",
        "find_module",
        "get_loader",
        "load_module",
        "create_module",
        "exec_module",
        "module_from_spec",
        "spec_from_file_location",
        "spec_from_loader",
        "LazyLoader",
        "SourceFileLoader",
        "SourcelessFileLoader",
        "ExtensionFileLoader",
        "FileFinder",
        "PathFinder",
        "zipimporter",
        "resolve_name",
        "walk_packages",
        "run_module",
        "run_path",
        "locate",
        # namespaces that hold the builtins, and so __import__ and exec
        "__builtins__",
        "__dict__",
        "__globals__",
        "__loader__",
        "__spec__",
    }
)
FORBIDDEN_NAMES = frozenset(
    {
        "__builtins__",
        "__import__",
        "__loader__",
        "__spec__",
        "compile",
        "eval",
        "exec",
        "globals",
        "locals",
        "vars",
    }
)
PATCH_CALLS = frozenset(
    {"unittest.mock.patch", "unittest.mock.patch.dict", "unittest.mock.patch.multiple"}
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


def _files(root: Path = PACKAGE) -> list[Path]:
    files = sorted(root.rglob("*.py"))
    assert len(files) > 10, f"no prototype files found under {root}"
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


# Dynamic-import check (MAR-259) ----------------------------------------------


def _is_machinery(module: str) -> bool:
    top = module.split(".")[0]
    return top in MACHINERY_MODULES or (
        top == "importlib" and module not in IMPORTLIB_FROM
    )


def _may_import_from(module: str, name: str) -> bool:
    """Whether ``from <module> import <name>`` (absolute) passes the check."""
    if module in IMPORTLIB_FROM:
        return name in IMPORTLIB_FROM[module]
    dotted = f"{module}.{name}"
    return name not in FORBIDDEN_ATTRIBUTES | FORBIDDEN_NAMES and not any(
        dotted == s or dotted.startswith(f"{s}.") for s in SYS_IMPORT_STATE
    )


def _bindings(tree: ast.Module) -> tuple[dict[str, str], list[str]]:
    """Map each name an absolute import binds to its dotted module or object.

    Also return the names bound to two different targets in the file, which
    the check refuses instead of guessing the scope.
    """
    bound: dict[str, str] = {}
    ambiguous: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            pairs = [
                (
                    a.asname or a.name.split(".")[0],
                    a.name if a.asname else a.name.split(".")[0],
                )
                for a in node.names
            ]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            pairs = [
                (a.asname or a.name, f"{node.module}.{a.name}") for a in node.names
            ]
        else:
            continue
        for name, target in pairs:
            if bound.setdefault(name, target) != target:
                ambiguous.append(f"{name} ({bound[name]} and {target})")
    return bound, ambiguous


def _docstrings(tree: ast.Module) -> set[ast.AST]:
    nodes: set[ast.AST] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                nodes.add(first.value)
    return nodes


class _DynamicImports(ast.NodeVisitor):
    """Collect the violations of one file, and the allowed calls it makes."""

    def __init__(self, tree: ast.Module, relative: str) -> None:
        self.relative = relative
        test = "test" in PurePosixPath(relative).parts
        self.allowed_modules = TEST_ALLOWED if test else LIBRARY_ALLOWED
        self.bindings, ambiguous = _bindings(tree)
        self.parents = {
            child: node
            for node in ast.walk(tree)
            for child in ast.iter_child_nodes(node)
        }
        self.docstrings = _docstrings(tree)
        self.scope: list[str] = []
        self.violations = [f"{relative}: name bound twice: {a}" for a in ambiguous]
        self.allowed_seen: set[tuple[str, str, str, str]] = set()
        self.visit(tree)

    # helpers

    def _fail(self, node: ast.expr | ast.stmt, reason: str) -> None:
        where = ".".join(self.scope) or "module level"
        self.violations.append(
            f"{self.relative}:{node.lineno} ({where}): {reason}: {ast.unparse(node)}"
        )

    def _resolve(self, expr: ast.expr) -> str | None:
        """Dotted name of an imported name or attribute chain, else ``None``."""
        if isinstance(expr, ast.Name):
            return self.bindings.get(expr.id)
        if isinstance(expr, ast.Attribute):
            base = self._resolve(expr.value)
            return None if base is None else f"{base}.{expr.attr}"
        return None

    def _module_allowed(self, name: str) -> bool:
        top = name.split(".")[0]
        return (
            top in sys.stdlib_module_names
            or top in self.allowed_modules
            or top == "petals_parametric"
        )

    def _check_chain(self, expr: ast.Name | ast.Attribute) -> None:
        """Check an outermost ``a.b.c`` chain (or a lone name)."""
        attributes: list[str] = []
        node: ast.expr = expr
        while isinstance(node, ast.Attribute):
            attributes.append(node.attr)
            node = node.value
        dotted = self._resolve(expr)
        parent = self.parents.get(expr)
        if (
            isinstance(parent, ast.Call)
            and parent.func is expr
            and dotted is not None
            and dotted in ALLOWED_CALLEES
        ):
            self._check_allowed_call(parent, dotted)
        elif dotted is not None and dotted.split(".")[0] == "importlib":
            self._fail(expr, "importlib used other than in an allowed call")
        elif dotted is not None and any(
            dotted == s or dotted.startswith(f"{s}.") for s in SYS_IMPORT_STATE
        ):
            self._fail(expr, "sys's import state")
        elif forbidden := sorted(FORBIDDEN_ATTRIBUTES.intersection(attributes)):
            self._fail(
                expr, f"import machinery or the builtins ({', '.join(forbidden)})"
            )

    def _check_allowed_call(self, call: ast.Call, callee: str) -> None:
        argument = call.args[0] if len(call.args) == 1 and not call.keywords else None
        literal = (
            argument.value
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
            else None
        )
        site = (self.relative, ".".join(self.scope), callee, literal)
        if literal is not None and site in ALLOWED_CALLS:
            self.allowed_seen.add((self.relative, site[1], callee, literal))
        else:
            self._fail(call, "dynamic import outside ALLOWED_CALLS")

    # scopes

    def _visit_scope(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    ) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = _visit_scope
    visit_AsyncFunctionDef = _visit_scope
    visit_ClassDef = _visit_scope

    # rules

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if _is_machinery(alias.name):
                self._fail(node, f"imports the import machinery ({alias.name})")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if node.level == 0 and _is_machinery(module):
            self._fail(node, f"imports the import machinery ({module})")
        for alias in node.names:
            if alias.name == "*":
                self._fail(node, "star import")
            elif node.level == 0 and not _may_import_from(module, alias.name):
                self._fail(node, f"imports {module}.{alias.name}")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            parent = self.parents.get(node)
            if node.id in FORBIDDEN_NAMES:
                self._fail(node, "code execution or the builtins")
            if node.id == "getattr" and not (
                isinstance(parent, ast.Call)
                and parent.func is node
                and len(parent.args) >= 2
                and isinstance(parent.args[1], ast.Constant)
                and isinstance(parent.args[1].value, str)
            ):
                self._fail(node, "getattr without a literal attribute name")
            if not (isinstance(parent, ast.Attribute) and parent.value is node):
                self._check_chain(node)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        parent = self.parents.get(node)
        if not (isinstance(parent, ast.Attribute) and parent.value is node):
            self._check_chain(node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        callee = self._resolve(node.func)
        if callee is not None and callee in PATCH_CALLS:
            keyword = "in_dict" if callee.endswith(".dict") else "target"
            target = node.args[0] if node.args else None
            for k in node.keywords:
                if k.arg == keyword:
                    target = k.value
            if not (
                isinstance(target, ast.Constant)
                and isinstance(target.value, str)
                and self._module_allowed(target.value)
            ):
                self._fail(node, "mock imports a patch target: use an allowed literal")
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        value = node.value
        if node in self.docstrings:
            return
        if (isinstance(value, str) and OWN_PREFIX in value) or (
            isinstance(value, bytes) and OWN_PREFIX.encode() in value
        ):
            self._fail(node, "string names this repository's packages")
        elif isinstance(value, str) and value in FORBIDDEN_ATTRIBUTES | FORBIDDEN_NAMES:
            self._fail(node, "string names the import machinery or the builtins")


def dynamic_import_violations(source: str, relative: str = "metrics.py") -> list[str]:
    """Violations of the dynamic-import check in ``source``.

    ``relative`` is the file's path in the package (``test/...`` for the
    tests): :data:`ALLOWED_CALLS` is keyed by it.
    """
    return _DynamicImports(ast.parse(source), relative).violations


def _scan(root: Path = PACKAGE) -> dict[str, _DynamicImports]:
    return {
        path.relative_to(root).as_posix(): _DynamicImports(
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path)),
            path.relative_to(root).as_posix(),
        )
        for path in _files(root)
    }


def tree_violations(root: Path = PACKAGE) -> dict[str, list[str]]:
    """Violations of every file under ``root``, keyed by its path in the package."""
    return {
        file: found.violations
        for file, found in _scan(root).items()
        if found.violations
    }


@pytest.mark.parametrize("path", _files(), ids=lambda p: str(p.relative_to(PACKAGE)))
def test_no_file_imports_dynamically(path: Path) -> None:
    relative = path.relative_to(PACKAGE).as_posix()
    assert dynamic_import_violations(path.read_text(encoding="utf-8"), relative) == []


def test_the_allowed_calls_are_still_made() -> None:
    """Every allow-listed site exists, so the allow-list cannot go stale."""
    seen = set().union(*(found.allowed_seen for found in _scan().values()))
    assert seen == ALLOWED_CALLS


@pytest.mark.parametrize(
    "source",
    [
        # 1. import calls, by every route
        "import importlib\nimportlib.import_module('parametric_insurance_design')",
        "import importlib\ndef f() -> None:\n"
        "    importlib.import_module('parametric_insurance_design_climada.pipeline')",
        "import importlib\nimportlib.__import__('parametric_insurance_design_viz')",
        "__import__('parametric_insurance_design_crc')",
        "m = __import__(name='json')",
        "load = __import__\nload('json')",
        "from importlib import import_module\nimport_module('json')",
        "from importlib import import_module as load\nload('cvxpy')",
        "import importlib as il\nil.import_module('cvxpy')",
        "import builtins\nbuiltins.__import__('json')",
        "from builtins import __import__ as load\nload('json')",
        "import sys\nsys.modules['importlib'].import_module('cvxpy')",
        "loader.import_module('json')",
        # 1. non-literal arguments, keywords, no argument
        "import importlib\nNAME = 'cvxpy'\nimportlib.import_module(NAME)",
        "import importlib\ndef f(pkg: str) -> None:\n"
        "    importlib.import_module(f'{pkg}.solve')",
        "import importlib\nimportlib.import_module('parametric_' + 'insurance_design')",
        "import importlib\nimportlib.import_module(*names)",
        "import importlib\nimportlib.import_module(name='cvxpy')",
        "import importlib\nimportlib.import_module('.x', package='petals_parametric')",
        "import importlib\nimportlib.import_module()",
        # 2. the rest of the import machinery
        "import importlib\nimportlib.reload(module)",
        "import importlib\nload = importlib.import_module",
        "import importlib\nmachinery = importlib",
        "import importlib\nimportlib.__dict__['import_module']",
        "import importlib.util\n"
        "spec = importlib.util.spec_from_file_location('m', 'solve.py')",
        "import importlib.util\nimportlib.util.module_from_spec(spec)",
        "import importlib.util as u\nu.find_spec('parametric_insurance_design')",
        "from importlib.util import spec_from_file_location",
        "from importlib.util import module_from_spec as load",
        "from importlib import machinery",
        "import importlib.machinery",
        "import importlib.resources\nimportlib.resources.files('petals_parametric')",
        "from importlib.metadata import entry_points",
        "import pkgutil",
        "from runpy import run_module",
        "import zipimport",
        "import code",
        "loader.exec_module(module)",
        "finder.find_spec('json', None)",
        "import sys\nsys.modules['parametric_insurance_design']",
        "import sys\nsys.meta_path.insert(0, finder)",
        "from sys import modules",
        "from importlib.util import find_spec as find\nfind('cvxpy')",
        # 3. code execution and the builtins
        "exec('import parametric_insurance_design')",
        "exec(source)",
        "eval('1 + 1')",
        "code = compile(text, 'f', 'exec')",
        "__builtins__.__import__('json')",
        "globals()['__builtins__']",
        "def f() -> None:\n    pass\nf.__globals__",
        "import numpy as np\nnp.__dict__",
        "getattr(obj, name)",
        "getattr(obj, 'import_' + 'module')",
        "from json import *",
        "import importlib as np\nimport numpy as np\nnp.import_module('cvxpy')",
        # 4. strings
        "PATH = 'parametric_insurance_design.solve'",
        "PATH = f'parametric_insurance_design.{name}'",
        "PICKLE = b'cparametric_insurance_design_climada'",
        "getattr(builtins_module, '__import__')",
        "namespace['exec']",
        # 5. mock.patch targets
        "from unittest import mock\nmock.patch('geopandas.read_file')",
        "from unittest import mock\nmock.patch(target)",
        "from unittest.mock import patch\npatch.dict(TABLE, {'cvxpy': None})",
        "import unittest.mock\nunittest.mock.patch.multiple(target=name, f=1)",
    ],
)
def test_the_dynamic_import_check_rejects(source: str) -> None:
    """Mutation probes: each source is one form the check must refuse."""
    assert dynamic_import_violations(source)


@pytest.mark.parametrize(
    "source",
    [
        "import numpy as np\nimport scipy.sparse as sp\n"
        "from climada.engine import Impact",
        "from petals_parametric.payout import StepPayout\nfrom .errors import X",
        "import importlib.util",
        "import re\nPATTERN = re.compile('a+')",
        "nit = getattr(result, 'nit', None)",
        "from unittest import mock\nmock.patch('petals_parametric.solvers.linprog')",
        "from unittest import mock\nmock.patch.dict('sys.modules', {'cvxpy': None})",
        "from unittest import mock\nmock.patch.object(solvers, 'linprog')",
        '"""A docstring may name parametric_insurance_design."""',
        "def f() -> None:\n    '''So may parametric_insurance_design_climada here.'''",
    ],
)
def test_the_dynamic_import_check_accepts(source: str) -> None:
    assert dynamic_import_violations(source) == []


def test_the_allow_list_is_keyed_by_file_function_and_argument() -> None:
    call = "import importlib\ndef {f}() -> None:\n    importlib.import_module({a})\n"
    allowed = call.format(f="_import_cvxpy", a="'cvxpy'")
    assert dynamic_import_violations(allowed, "solvers.py") == []
    assert dynamic_import_violations(allowed, "metrics.py")
    assert dynamic_import_violations(call.format(f="_other", a="'cvxpy'"), "solvers.py")
    assert dynamic_import_violations(
        call.format(f="_import_cvxpy", a="'scipy'"), "solvers.py"
    )
    assert dynamic_import_violations(
        call.format(f="_import_cvxpy", a="CVXPY"), "solvers.py"
    )
    find = "import importlib.util\nHAS_CVXPY = importlib.util.find_spec({a}) is None\n"
    test_calibrate = "test/test_calibrate.py"
    assert dynamic_import_violations(find.format(a="'cvxpy'"), test_calibrate) == []
    assert dynamic_import_violations(find.format(a="'cvxpy'"), "test/test_metrics.py")
    assert dynamic_import_violations(find.format(a="'cvxpy.x'"), test_calibrate)


def _mutate(source: str, function: str, statements: str) -> str:
    """Insert ``statements`` at the top of ``function``'s body (after its docstring)."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == function
        ):
            start = 1 if ast.get_docstring(node) is not None else 0
            node.body[start:start] = ast.parse(statements).body
            return ast.unparse(tree)
    raise AssertionError(f"no function {function!r}")


@pytest.mark.parametrize(
    ("relative", "function", "statements"),
    [
        pytest.param(
            "metrics.py",
            "basis_risk",
            "import importlib\n"
            "importlib.import_module('parametric_insurance_design.metrics')",
            id="metrics-import_module",
        ),
        pytest.param(
            "solvers.py",
            "_solve_qp",
            "__import__('parametric_insurance_design_climada')",
            id="mse-path-__import__",
        ),
        pytest.param(
            "solvers.py",
            "_import_cvxpy",
            "importlib.import_module(CORE)",
            id="allowed-site-non-literal",
        ),
        pytest.param(
            "test/test_metrics.py",
            "setUp",
            "exec('import parametric_insurance_design_viz')",
            id="test-exec",
        ),
    ],
)
def test_the_check_fires_on_a_mutated_copy(
    tmp_path: Path, relative: str, function: str, statements: str
) -> None:
    """A dynamic import in a function the run-time check never calls is caught."""
    copy = tmp_path / "petals_parametric"
    shutil.copytree(PACKAGE, copy, ignore=shutil.ignore_patterns("__pycache__"))
    assert tree_violations(copy) == {}
    target = copy / relative
    mutated = _mutate(target.read_text(encoding="utf-8"), function, statements)
    target.write_text(mutated, encoding="utf-8")
    # the static checks (this file's and TID251) see no import of our packages
    assert all(module not in OWN_PACKAGES for _, module in _imports(target))
    found = tree_violations(copy)
    assert list(found) == [relative]
    assert all(f"({function}" in v or f".{function})" in v for v in found[relative])


# Run-time check ----------------------------------------------------------------


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
