#!/usr/bin/env python3
"""Refuse a ``start_session`` that would run somewhere else (MAR-289).

A Claude Code ``PreToolUse`` hook, wired in ``.claude/settings.json`` on the
one tool ``mcp__ccd_session__start_session`` (Marc's decision on MAR-282). A
session started in another folder, on another host or in the cloud runs
without this repository's deny rules and hooks. A deny rule can't say so:
settings skip ``mcp__`` rules with parentheses, so only a hook can read the
tool's parameters.

The hook refuses a call that sets ``cwd``, ``host``, ``preset``,
``environment`` or ``repository`` to anything present and non-empty (``None``,
``""``, ``[]`` and ``{}`` count as not set), or a ``target`` other than
``"local"``. Every other field passes, so ``start_session`` keeps its use in
"Delegating to subagents" (``docs/ORCHESTRATION.md``).

**It fails closed.** Input that isn't a ``PreToolUse`` JSON object for this
tool with a ``tool_input`` object, and any exception, refuses the call. If
``python3`` is missing the hook can't start, and Claude Code treats that as a
non-blocking error and runs the tool: the fork gh guard has the same limit.
If the app renames these parameters, the hook passes the new names until it
is updated.

Contract (Claude Code hooks reference): the hook reads the ``PreToolUse`` JSON
on stdin and refuses a call by exiting 2 with the reason on stderr, which
Claude sees. It never exits with another code. It needs only the standard
library and runs on Python 3.9 or later, as ``python3 -I``. Its tests are in
``scripts/check_fork_gh_guard.py``.
"""

from __future__ import annotations

import json
import sys

TOOL = "mcp__ccd_session__start_session"
# The parameters that put a session somewhere else.
PLACE_FIELDS = ("cwd", "host", "preset", "environment", "repository")
LOCAL_TARGET = "local"
_PREFIX = "Refused by the session guard (.claude/hooks/session_guard.py, MAR-289):"


class MalformedInput(ValueError):
    """The hook input isn't a ``PreToolUse`` call of ``start_session``."""


def is_set(value: object) -> bool:
    """Return whether a parameter is present and non-empty.

    Parameters
    ----------
    value
        The parameter's value, or ``None`` if it is absent.

    Returns
    -------
    bool
        ``False`` for ``None``, ``""``, ``[]`` and ``{}``, else ``True``.
    """
    return value is not None and value not in ("", [], {})


def refused_fields(tool_input: dict[str, object]) -> list[str]:
    """Return the parameters that would run the session somewhere else.

    Parameters
    ----------
    tool_input
        The tool's input.

    Returns
    -------
    list of str
        Each refused parameter with its value, in the order of
        ``PLACE_FIELDS``, then ``target``.
    """
    found = [
        f"{name}={tool_input[name]!r}"
        for name in PLACE_FIELDS
        if is_set(tool_input.get(name))
    ]
    target = tool_input.get("target")
    if is_set(target) and target != LOCAL_TARGET:
        found.append(f"target={target!r}")
    return found


def check(payload: object) -> str | None:
    """Return the refusal message for a hook input, or ``None`` to allow it.

    Parameters
    ----------
    payload
        The parsed hook input.

    Returns
    -------
    str or None
        Why the call is refused and how to fix it, or ``None``.

    Raises
    ------
    MalformedInput
        If ``payload`` isn't a ``PreToolUse`` call of this tool.
    """
    if not isinstance(payload, dict):
        raise MalformedInput("the hook input is not a JSON object")
    if payload.get("tool_name") != TOOL:
        raise MalformedInput(f"tool_name is {payload.get('tool_name')!r}, not {TOOL}")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        raise MalformedInput("the hook input has no tool_input object")
    fields = refused_fields(tool_input)
    if not fields:
        return None
    return "\n".join(
        [
            _PREFIX,
            f"start_session would run somewhere else: {', '.join(fields)}.",
            "A session started elsewhere runs without this repository's deny rules",
            "and hooks, so agents start sessions only here.",
            "Fix: call it without cwd, host, preset, environment or repository, and",
            'with no target other than "local". Other places are Marc\'s to start.',
        ]
    )


def main() -> int:
    """Run the hook: read the input on stdin, exit 2 to refuse, 0 to allow.

    Returns
    -------
    int
        The exit status: 0 if the call may run, 2 otherwise, including on any
        failure of the hook.
    """
    try:
        message = check(json.loads(sys.stdin.read()))
    except Exception as exc:  # fails closed: this hook guards one tool only
        problem = f"{type(exc).__name__}: {exc}"
        if len(problem) > 200:
            problem = problem[:197] + "..."
        message = "\n".join(
            [
                _PREFIX,
                f"the hook couldn't check this start_session call ({problem}),",
                "so it refuses it.",
                "Fix: report the error to the orchestrator, so that the hook is fixed",
                "and a case added to scripts/check_fork_gh_guard.py.",
            ]
        )
    if message is None:
        return 0
    sys.stderr.write(message + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
