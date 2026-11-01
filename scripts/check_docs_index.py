#!/usr/bin/env python3
"""Check that ``docs/README.md`` indexes every tracked file under ``docs/`` (MAR-191).

``docs/README.md`` is the entry page of the documentation (ADR 0004, MAR-186).
A page that it doesn't link is hard for a visitor to find. Rules, for every
file in ``git ls-files docs/`` other than the index itself:

- a Markdown file must be linked **directly** from ``docs/README.md``;
- any other file (a figure) must be linked directly, or linked or embedded by
  a page that ``docs/README.md`` links directly (one hop).

Links are inline Markdown links and images (``[text](target)``,
``![alt](target)``) and HTML ``src``/``href`` attributes. External targets
(with a URL scheme) and in-page anchors are ignored; ``#anchor`` and
``?query`` suffixes are stripped. Targets resolve relative to the page that
holds them.

Usage::

    python3 scripts/check_docs_index.py [--self-test] [ROOT]

ROOT defaults to the repository root (the parent of this script's folder).
``--self-test`` first runs the rules on built-in probe trees, expecting each to
pass or fail as labelled, so that a broken rule fails too. Exit status: 0 if
all is as expected, 1 otherwise. Standard library only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path, PurePosixPath

INDEX = "docs/README.md"

_MD_LINK = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_HTML_ATTR = re.compile(r"""\b(?:src|href)\s*=\s*["']([^"']+)["']""")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def link_targets(page: str, text: str) -> set[str]:
    """Return the repository paths that ``page`` links or embeds.

    Parameters
    ----------
    page
        Repository-relative POSIX path of the page, e.g. ``docs/README.md``.
    text
        The page's content.

    Returns
    -------
    set of str
        Normalised repository-relative paths. Targets that leave the
        repository root are dropped, since they can't be tracked files.
    """
    base = PurePosixPath(page).parent
    out: set[str] = set()
    for raw in [*_MD_LINK.findall(text), *_HTML_ATTR.findall(text)]:
        target = raw.split("#", 1)[0].split("?", 1)[0]
        if not target or _SCHEME.match(target) or target.startswith("/"):
            continue
        parts: list[str] = []
        escaped = False
        for part in (base / target).parts:
            if part in ("", "."):
                continue
            if part == "..":
                if not parts:
                    escaped = True
                    break
                parts.pop()
            else:
                parts.append(part)
        if not escaped and parts:
            out.add("/".join(parts).rstrip("/"))
    return out


def check(files: Iterable[str], read: Callable[[str], str]) -> list[str]:
    """Return one error line per file under ``docs/`` the index misses.

    Parameters
    ----------
    files
        Tracked repository-relative paths (at least those under ``docs/``).
    read
        Returns the text of a tracked page, given its path.

    Returns
    -------
    list of str
        Empty if every file is indexed.
    """
    tracked = set(files)
    if INDEX not in tracked:
        return [f"{INDEX} is missing"]
    direct = link_targets(INDEX, read(INDEX))
    one_hop: set[str] = set()
    for page in sorted(direct):
        if page in tracked and page.endswith(".md"):
            one_hop |= link_targets(page, read(page))
    errors: list[str] = []
    for path in sorted(p for p in tracked if p.startswith("docs/") and p != INDEX):
        if path in direct:
            continue
        if path.endswith(".md"):
            errors.append(f"{path}: Markdown page not linked from {INDEX}")
        elif path not in one_hop:
            errors.append(
                f"{path}: not linked from {INDEX} or from a page it links directly"
            )
    return errors


def _self_test() -> bool:
    """Run the rules on probe trees; return True if each behaves as labelled."""
    figure = "docs/m/figures/f.png"
    good = {
        INDEX: "[A](a.md) and [M](m/page.md#x) and [root](../README.md)",
        "docs/a.md": "text",
        "docs/m/page.md": "![f](figures/f.png)",
        figure: "",
        "docs/figures/s.svg": "",
        "README.md": '<img src="docs/figures/s.svg">',
    }
    missing_page = {**good, "docs/b.md": "orphan"}
    missing_figure = {**good, "docs/m/page.md": "no image"}
    # index -> docs/a.md -> other/n.md (outside docs/) -> docs/g.png
    two_hops = {
        **good,
        "docs/a.md": "[n](../other/n.md)",
        "other/n.md": "![g](../docs/g.png)",
        "docs/g.png": "",
    }
    probes: list[tuple[str, dict[str, str], bool]] = [
        ("all indexed (direct, one hop, via the root README)", good, True),
        ("an unlinked Markdown page", missing_page, False),
        ("a figure no linked page shows", missing_figure, False),
        ("a figure two hops away", two_hops, False),
    ]
    ok = True
    for label, tree, should_pass in probes:
        passed = not check(tree, tree.__getitem__)
        status = "ok  " if passed == should_pass else "FAIL"
        expected = "pass" if should_pass else "fail"
        print(f"self-test {status} expect {expected}: {label}")
        ok &= passed == should_pass
    return ok


def main(argv: list[str] | None = None) -> int:
    """Run the check (and optionally the self-test); return the exit status."""
    parser = argparse.ArgumentParser(
        description="Check that docs/README.md indexes every file under docs/."
    )
    parser.add_argument("root", nargs="?", default=None)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    ok = True
    if args.self_test:
        ok = _self_test()
    root = args.root or str(Path(__file__).resolve().parent.parent)
    listed = subprocess.run(
        ["git", "-C", root, "ls-files", "-z"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split("\0")
    files = [f for f in listed if f]

    def read(path: str) -> str:
        with open(f"{root}/{path}", encoding="utf-8") as fh:
            return fh.read()

    errors = check(files, read)
    for line in errors:
        print(line)
    n_docs = sum(1 for f in files if f.startswith("docs/") and f != INDEX)
    print(f"{n_docs} files under docs/ checked against {INDEX}: {len(errors)} missing")
    return 0 if ok and not errors else 1


if __name__ == "__main__":
    sys.exit(main())
