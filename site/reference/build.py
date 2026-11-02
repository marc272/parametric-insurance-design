"""Build the site's API reference with quartodoc (ADR 0004 Q4, R1).

Run it from the repository root, before ``quarto render site``::

    uv run --locked --group docs python site/reference/build.py

It runs ``quartodoc build`` on the ``quartodoc`` section of
``site/_quarto.yml``, which writes one page per entry into ``site/reference/``
and the sidebar ``site/reference/_sidebar.yml``. Then it

1. labels each module in the sidebar by its path in the package
   (``evaluate``, ``experiment.config``): modules are listed by their full
   names, which the sidebar would cut off;
2. checks that every name of ``pid.__all__`` has its page, so a name added to
   the public API without a reference entry fails the build.

quartodoc's inventory (``objects.json``) goes into ``site/reference/`` too;
the site doesn't publish it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import ModuleType

import yaml
from quartodoc import Builder

import parametric_insurance_design as pid

SITE = Path(__file__).resolve().parents[1]
REFERENCE = SITE / "reference"
SIDEBAR = REFERENCE / "_sidebar.yml"
MODULE_PREFIX = f"reference/{pid.__name__}."


def build() -> None:
    """Run ``quartodoc build`` from ``site/``, where its paths are relative."""
    os.chdir(SITE)
    builder = Builder.from_quarto_config("_quarto.yml")
    builder.out_inventory = "reference/objects.json"
    builder.build()


def label_modules(entry: object) -> object:
    """Return a sidebar entry with each module page labelled by its path."""
    if isinstance(entry, str) and entry.startswith(MODULE_PREFIX):
        module = entry.removeprefix(MODULE_PREFIX).removesuffix(".qmd")
        return {"href": entry, "text": module}
    if isinstance(entry, dict):
        return {key: label_modules(value) for key, value in entry.items()}
    if isinstance(entry, list):
        return [label_modules(item) for item in entry]
    return entry


def page(name: str) -> Path:
    """Return the page of a name of ``pid.__all__``."""
    if isinstance(getattr(pid, name), ModuleType):
        return REFERENCE / f"{pid.__name__}.{name}.qmd"
    return REFERENCE / f"{name}.qmd"


def main() -> int:
    """Build the reference, label the sidebar's modules and check the pages."""
    build()
    sidebar = yaml.safe_load(SIDEBAR.read_text(encoding="utf-8"))
    SIDEBAR.write_text(
        yaml.safe_dump(label_modules(sidebar), sort_keys=False), encoding="utf-8"
    )
    names = [name for name in pid.__all__ if name != "__version__"]
    missing = [name for name in names if not page(name).is_file()]
    if missing or not (REFERENCE / "index.qmd").is_file():
        print(f"API reference: no page for {missing or 'the index'}", file=sys.stderr)
        return 1
    n_pages = len(list(REFERENCE.glob("*.qmd")))
    print(
        f"API reference: {n_pages} pages in {REFERENCE.relative_to(SITE.parent)}; "
        f"every name of pid.__all__ ({len(names)}) has one"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
