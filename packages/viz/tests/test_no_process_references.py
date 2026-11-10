"""The viz package's strings cite no internal project documents.

The viz package ships to PyPI with the core. Its error messages, figure
notes, site-bundle labels and docstrings must state facts, not point to the
project's decision records, specification sections, issue tracker or thesis
issue codes, which a user of the package or a reader of the website cannot
read. This test parses every module of the package with :mod:`ast` and checks
every string constant: module, class and function docstrings, messages,
figure and bundle texts and the literal parts of f-strings.

* Comments are not strings, so they may keep their references.
* Citations of the thesis's own sections ("thesis §3.3") are allowed: the
  thesis is the method's published source.

The core has the same check (``packages/core/tests``); test modules cannot
import each other under ``--import-mode=importlib``, so the scan is repeated
here.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import pytest

PACKAGE = "parametric_insurance_design_viz"

REFERENCE = re.compile(r"ADR 0|SPEC §|thesis issue|MAR-[0-9]")
"""What a string must not contain: a decision record (``ADR 0002``), a
specification section (``SPEC §5``), a thesis issue code (``thesis issue M2``)
or an issue ID (``MAR-123``)."""


@dataclass(frozen=True, order=True)
class Hit:
    """One reference found in a string constant."""

    path: str
    line: int
    match: str
    text: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.match!r} in {self.text!r}"


def find_references(source: str, path: str) -> list[Hit]:
    """Return the references in the string constants of one module's source.

    Parameters
    ----------
    source
        The module's source code.
    path
        The name to report the hits under.

    Returns
    -------
    list of Hit
        One per match, sorted by line. The line is the string's first line
        plus the line breaks before the match, at most the string's last line.
    """
    hits: list[Hit] = []
    for node in ast.walk(ast.parse(source, filename=path)):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        last = node.end_lineno if node.end_lineno is not None else node.lineno
        for offset, text in enumerate(node.value.splitlines()):
            for match in REFERENCE.finditer(text):
                line = min(node.lineno + offset, last)
                hits.append(Hit(path, line, match.group(), text.strip()))
    return sorted(hits)


def scan_package(root: Path) -> list[Hit]:
    """Return the references in every ``.py`` file under ``root``.

    Paths are reported relative to ``root``'s parent, e.g.
    ``parametric_insurance_design/cli.py``.
    """
    hits: list[Hit] = []
    for module in sorted(root.rglob("*.py")):
        name = module.relative_to(root.parent).as_posix()
        hits.extend(find_references(module.read_text(encoding="utf-8"), name))
    return hits


def report(hits: list[Hit]) -> str:
    """The failure message: one line per hit, file, line and matched text."""
    lines = "\n".join(f"  {hit}" for hit in hits)
    return (
        f"{len(hits)} string(s) cite internal project documents; state the "
        f"fact the reference stands for instead (comments may keep it):\n{lines}"
    )


def _package_root() -> Path:
    return Path(str(files(PACKAGE)))


def test_package_strings_cite_no_internal_documents() -> None:
    root = _package_root()
    assert (root / "__init__.py").is_file()
    hits = scan_package(root)
    assert not hits, report(hits)


PLANTED = [
    pytest.param('"""Module docstring (SPEC §5)."""\n', 1, "SPEC §", id="module"),
    pytest.param(
        'class A:\n    """One.\n\n    Two (ADR 0002 §6).\n    """\n',
        4,
        "ADR 0",
        id="class-docstring-line",
    ),
    pytest.param(
        'def f():\n    """See thesis issue M2."""\n',
        2,
        "thesis issue",
        id="function",
    ),
    pytest.param('raise ValueError("added in MAR-187")\n', 1, "MAR-1", id="message"),
    pytest.param('x = 1\nmsg = f"x is {x} (SPEC §6.2)"\n', 2, "SPEC §", id="f-string"),
]


@pytest.mark.parametrize(("source", "line", "match"), PLANTED)
def test_the_scan_finds_a_planted_reference(source: str, line: int, match: str) -> None:
    hits = find_references(source, "planted.py")
    assert [(hit.path, hit.line, hit.match) for hit in hits] == [
        ("planted.py", line, match)
    ]


def test_the_scan_fails_on_a_planted_file(tmp_path: Path) -> None:
    root = tmp_path / "pkg"
    (root / "sub").mkdir(parents=True)
    (root / "__init__.py").write_text('"""Clean."""\n', encoding="utf-8")
    (root / "sub" / "mod.py").write_text(
        'x = 1\n\n\ndef f():\n    raise ValueError("see SPEC §5")\n',
        encoding="utf-8",
    )
    hits = scan_package(root)
    assert hits == [Hit("pkg/sub/mod.py", 5, "SPEC §", "see SPEC §5")]
    assert report(hits) == (
        "1 string(s) cite internal project documents; state the fact the "
        "reference stands for instead (comments may keep it):\n"
        "  pkg/sub/mod.py:5: 'SPEC §' in 'see SPEC §5'"
    )


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("# SPEC §5, ADR 0002 §6, MAR-187\nx = 1\n", id="comment"),
        pytest.param('"""As in thesis §3.3 (3)."""\n', id="thesis-section"),
        pytest.param('MARKERS = ("MARKER_COLUMNS", "A1", "C1")\n', id="names"),
        pytest.param('x = b"SPEC \\xc2\\xa7 MAR-1"\n', id="bytes"),
    ],
)
def test_the_scan_allows(source: str) -> None:
    assert find_references(source, "allowed.py") == []
