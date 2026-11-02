"""pytest setup for ``parity/``.

Markers
    ``parity``
        The fast parity subset. CI runs it on every pull request
        (``uv run --locked pytest parity/tests``). Every test under
        ``parity/`` that is not marked ``parity_full`` gets this marker here,
        so ``-m parity`` selects exactly that subset.
    ``parity_full``
        Slow parity runs (solving the thesis experiment),
        meant for a nightly or manual job. They are skipped unless they are
        asked for: with ``-m parity_full`` (or any ``-m`` expression that
        names the marker) or with the environment variable
        ``PARITY_FULL=1``.

The markers are registered here rather than in the root ``pyproject.toml``,
which other issues edit. pytest runs with ``strict = true``, so an
unregistered marker would be an error.

This file also puts ``parity/`` on ``sys.path`` so that the tests can import
the parity tooling (``harness``, ``report``) as top-level modules, the same
way ``python parity/report.py`` sees them.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PARITY_DIR = Path(__file__).resolve().parent
FULL_ENV = "PARITY_FULL"

if str(PARITY_DIR) not in sys.path:
    sys.path.insert(0, str(PARITY_DIR))


def pytest_configure(config: pytest.Config) -> None:
    """Register the parity markers."""
    config.addinivalue_line(
        "markers", "parity: fast parity check, runs on every pull request"
    )
    config.addinivalue_line(
        "markers",
        "parity_full: slow parity run; skipped unless selected with "
        f"-m parity_full or {FULL_ENV}=1",
    )


def _full_requested(config: pytest.Config) -> bool:
    """Whether the run asked for the ``parity_full`` tests."""
    if os.environ.get(FULL_ENV, "").strip() not in ("", "0"):
        return True
    expression = str(config.getoption("markexpr", default="") or "")
    return "parity_full" in expression


# tryfirst: the markers must be in place before pytest's own -m deselection.
@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Mark the fast subset ``parity``; skip ``parity_full`` unless requested."""
    full = _full_requested(config)
    skip_full = pytest.mark.skip(
        reason=f"parity_full is slow: select it with -m parity_full or {FULL_ENV}=1"
    )
    for item in items:
        if not item.path.is_relative_to(PARITY_DIR):
            continue
        if item.get_closest_marker("parity_full") is None:
            item.add_marker(pytest.mark.parity)
        elif not full:
            item.add_marker(skip_full)
