#!/usr/bin/env python3
"""Check that pre-commit runs ruff only from uv.lock (MAR-77).

The ruff hooks in ``.pre-commit-config.yaml`` are local hooks whose entry is
``uv run --locked ruff check`` or ``uv run --locked ruff format``, so the
ruff that pre-commit runs is the one in ``uv.lock``: there is no second ruff
version to keep in sync. This script fails if that stops being true, e.g. if
someone adds astral-sh/ruff-pre-commit back with its own ``rev``, or a hook
runs a bare ``ruff`` from PATH.

Rules, for every hook that runs ruff (its repo, id or entry names ruff):

- the hook is in ``repo: local``;
- its language is ``system`` (or its new name, ``unsupported``);
- its entry starts with ``uv run --locked ruff check`` or
  ``uv run --locked ruff format``.

Both a ``ruff check`` and a ``ruff format`` hook must exist.

Usage::

    uv run --locked scripts/check_ruff_single_source.py [--self-test] [CONFIG]

CONFIG defaults to ``.pre-commit-config.yaml`` at the repository root.
``--self-test`` first runs the rules on built-in probe configs, expecting each
to pass or fail as labelled, so that a broken rule fails CI too (like
``scripts/check_import_boundaries.sh``). Exit status: 0 if all is as
expected, 1 otherwise.
"""

from __future__ import annotations

import argparse
import shlex
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
SYSTEM_LANGUAGES = {"system", "unsupported"}
LOCKED_PREFIX = ["uv", "run", "--locked", "ruff"]


def locked_ruff_version(lock_path: Path) -> str:
    """Return the ruff version pinned in ``uv.lock``.

    Parameters
    ----------
    lock_path
        Path to ``uv.lock``.

    Returns
    -------
    str
        The locked ruff version, e.g. ``"0.17.2"``.

    Raises
    ------
    LookupError
        If ``uv.lock`` has no ruff package.
    """
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    for package in lock.get("package", []):
        if package.get("name") == "ruff":
            return str(package["version"])
    raise LookupError(f"no ruff package in {lock_path}")


def _runs_ruff(repo_url: str, hook: dict[str, Any]) -> bool:
    if "ruff" in repo_url.lower() or "ruff" in str(hook.get("id", "")).lower():
        return True
    tokens = shlex.split(str(hook.get("entry", "")))
    return any(t == "ruff" or t.endswith("/ruff") for t in tokens)


def check_config(config: dict[str, Any], ruff_version: str) -> list[str]:
    """Return the rule violations in a parsed pre-commit config.

    Parameters
    ----------
    config
        The parsed ``.pre-commit-config.yaml``.
    ruff_version
        The ruff version in ``uv.lock``, quoted in the messages.

    Returns
    -------
    list of str
        One message per violation; empty if the config follows the rules.
    """
    errors: list[str] = []
    seen: set[str] = set()
    for repo in config.get("repos") or []:
        url = str(repo.get("repo", ""))
        for hook in repo.get("hooks") or []:
            if not _runs_ruff(url, hook):
                continue
            hook_id = hook.get("id", "?")
            if url != "local":
                errors.append(
                    f"hook {hook_id!r} runs ruff from {url} at rev "
                    f"{repo.get('rev')!r}, a second ruff version next to uv.lock's "
                    f"{ruff_version}; use a local hook with entry "
                    "'uv run --locked ruff ...'"
                )
                continue
            language = hook.get("language")
            if language not in SYSTEM_LANGUAGES:
                errors.append(
                    f"hook {hook_id!r} has language {language!r}; it must be "
                    "'system' so that uv runs the locked ruff"
                )
            tokens = shlex.split(str(hook.get("entry", "")))
            command = (
                tokens[len(LOCKED_PREFIX)] if len(tokens) > len(LOCKED_PREFIX) else None
            )
            if tokens[: len(LOCKED_PREFIX)] != LOCKED_PREFIX or command not in {
                "check",
                "format",
            }:
                errors.append(
                    f"hook {hook_id!r} has entry {hook.get('entry')!r}; it must "
                    "start with 'uv run --locked ruff check' or "
                    "'uv run --locked ruff format'"
                )
            elif language in SYSTEM_LANGUAGES:
                seen.add(command)
    for command in ("check", "format"):
        if command not in seen:
            errors.append(f"no hook runs 'uv run --locked ruff {command}'")
    return errors


def _local(*hooks: dict[str, Any]) -> dict[str, Any]:
    return {"repos": [{"repo": "local", "hooks": list(hooks)}]}


def _hook(command: str, entry: str | None = None, **extra: object) -> dict[str, Any]:
    hook: dict[str, Any] = {
        "id": f"ruff-{command}",
        "name": f"ruff {command}",
        "entry": entry or f"uv run --locked ruff {command} --force-exclude",
        "language": "system",
    }
    hook.update(extra)
    return hook


def _probes(ruff_version: str) -> list[tuple[str, str, dict[str, Any]]]:
    """Return (expected, label, config) cases for the self-test."""
    good = [_hook("check", args=["--fix"]), _hook("format")]
    remote = {
        "repo": "https://github.com/astral-sh/ruff-pre-commit",
        "hooks": [{"id": "ruff-check"}, {"id": "ruff-format"}],
    }
    other_hooks = {
        "repo": "https://github.com/pre-commit/pre-commit-hooks",
        "rev": "v6.0.0",
        "hooks": [{"id": "check-yaml"}],
    }
    return [
        ("ok", "local uv-run hooks", _local(*good)),
        (
            "ok",
            "language 'unsupported' (system's new name)",
            _local(*(dict(h, language="unsupported") for h in good)),
        ),
        (
            "ok",
            "plus unrelated remote hooks",
            {"repos": [other_hooks, *_local(*good)["repos"]]},
        ),
        (
            "fail",
            "remote ruff-pre-commit at the locked rev",
            {"repos": [dict(remote, rev=f"v{ruff_version}")]},
        ),
        (
            "fail",
            "remote ruff-pre-commit next to the local hooks",
            {"repos": [dict(remote, rev="v0.0.1"), *_local(*good)["repos"]]},
        ),
        (
            "fail",
            "bare ruff from PATH",
            _local(_hook("check", entry="ruff check"), good[1]),
        ),
        (
            "fail",
            "uv run without --locked",
            _local(good[0], _hook("format", entry="uv run ruff format")),
        ),
        (
            "fail",
            "language python with its own ruff",
            _local(
                dict(good[0], language="python", additional_dependencies=["ruff"]),
                good[1],
            ),
        ),
        ("fail", "no format hook", _local(good[0])),
        ("fail", "no ruff hooks at all", {"repos": [other_hooks]}),
    ]


def self_test(ruff_version: str) -> bool:
    """Run the rules on the probe configs; return True if all behave."""
    passed = True
    probes = _probes(ruff_version)
    for expected, label, config in probes:
        errors = check_config(config, ruff_version)
        got = "fail" if errors else "ok"
        if got == expected:
            print(f"ok   [{expected}] {label}")
        else:
            passed = False
            print(f"FAIL [{expected}, got {got}] {label}")
            for error in errors:
                print(f"    {error}")
    print(
        f"self-test: {'all' if passed else 'NOT all'} {len(probes)} probes as expected"
    )
    return passed


def main(argv: list[str] | None = None) -> int:
    """Run the check; see the module docstring.

    Parameters
    ----------
    argv
        Command-line arguments (default: ``sys.argv[1:]``).

    Returns
    -------
    int
        Exit status: 0 if all is as expected, 1 otherwise.
    """
    parser = argparse.ArgumentParser(
        description="Check that pre-commit runs ruff only from uv.lock."
    )
    parser.add_argument("config", nargs="?", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    ruff_version = locked_ruff_version(ROOT / "uv.lock")
    ok = self_test(ruff_version) if args.self_test else True

    path: Path = args.config or ROOT / ".pre-commit-config.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    errors = check_config(config, ruff_version)
    for error in errors:
        print(f"FAIL {path.name}: {error}")
    if errors:
        ok = False
    else:
        print(
            f"check_ruff_single_source: {path.name} runs ruff only via "
            f"'uv run --locked' (uv.lock: ruff {ruff_version})"
        )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
