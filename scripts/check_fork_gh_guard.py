#!/usr/bin/env python3
"""Test the fork gh guard hook, ``.claude/hooks/fork_gh_guard.py`` (MAR-253).

The hook refuses a repo-scoped ``gh`` command (``gh pr``, ``issue``,
``label``, ``run``, ``secret``, ``variable``, ``cache``) that may run in a CRC
fork path without ``--repo marc272/<fork>``, and a ``gh api`` call there that
uses the ``{owner}``/``{repo}`` placeholders (MAR-261). This script runs it
the way Claude Code does, one process per case with the ``PreToolUse`` JSON
on stdin, and checks the exit status: 0 allows with no output, 2 refuses with
a message on stderr that says how to fix the command. It also checks that:

- ``.claude/settings.json`` wires the hook as one ``PreToolUse`` hook whose
  matcher names Bash, Monitor and the terminal tool, by running its command
  string through ``sh -c`` with ``CLAUDE_PROJECT_DIR`` set, as Claude Code
  does; that it keeps its deny rules; and that it denies the terminal tool;
- the hook parses with Python 3.9's grammar, the oldest ``python3`` it may get
  (macOS's ``/usr/bin/python3``);
- Monitor and terminal-tool calls are checked like Bash calls, a Monitor
  WebSocket watch and other tools pass, and bad input (not JSON, no command)
  is refused when it mentions a checked gh command.

No path needs to exist: the cases use the owner's paths, and the hook compares
paths as text.

Usage::

    uv run --locked scripts/check_fork_gh_guard.py [--python PYTHON] [--markdown]

``--python`` runs the hook cases with another interpreter, e.g.
``/usr/bin/python3`` (default: the one running this script). ``--markdown``
also prints the cases as a Markdown table. Exit status: 0 if everything is as
expected, 1 otherwise. Standard library only.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / ".claude" / "hooks" / "fork_gh_guard.py"
SETTINGS = ROOT / ".claude" / "settings.json"

# The keys that the published settings schema allows in a command hook and in
# a matcher group: https://json.schemastore.org/claude-code-settings.json,
# $defs/hookCommand ("Bash command hook") and $defs/hookMatcher, both with
# additionalProperties: false. A key outside them risks Claude Code rejecting
# the whole settings file, deny rules included. "onFailure", documented in
# the hooks reference for v2.1.295+, isn't in the schema (MAR-253 review).
HOOK_COMMAND_KEYS = frozenset(
    {
        "args",
        "async",
        "asyncRewake",
        "command",
        "if",
        "shell",
        "statusMessage",
        "timeout",
        "type",
    }
)
HOOK_MATCHER_KEYS = frozenset({"matcher", "hooks"})
HOOK_PROBE = {"type": "command", "command": "true"}
# Only --repo or -R may pick the repository of a gh command (MAR-253).
GH_REPO_DENY_RULES = (
    "Bash(GH_REPO=*)",
    "Bash(env GH_REPO=*)",
    "Bash(export GH_REPO*)",
)
# The tools that run shell commands, which the guard's matcher must name
# (MAR-261). Monitor uses Bash's permission rules; the desktop app's terminal
# tool runs in the user's login shell, outside them, so it is also denied.
TERMINAL_TOOL = "mcp__terminal__run_in_terminal"
GUARDED_TOOLS = ("Bash", "Monitor", TERMINAL_TOOL)
# The hooks reference, "Matcher patterns": a matcher of only these characters
# is an exact tool name, or a list of them separated by | or ,; any other
# character makes it an unanchored JavaScript regular expression.
EXACT_MATCHER = re.compile(r"[A-Za-z0-9_\-, |]*")

# Loads the hook as a module, makes evaluate() raise, and runs main(), so
# that main's handling of an internal error runs in a real hook process.
FORCE_INTERNAL_ERROR = """\
import importlib.util, sys
spec = importlib.util.spec_from_file_location("fork_gh_guard", sys.argv[1])
hook = importlib.util.module_from_spec(spec)
sys.modules["fork_gh_guard"] = hook
spec.loader.exec_module(hook)
def broken(*args, **kwargs):
    raise RuntimeError("forced by check_fork_gh_guard")
hook.evaluate = broken
sys.exit(hook.main())
"""

HOME = "/Users/marcprinzing"
WS = f"{HOME}/Parametric_Insurance"
FORKS = f"{WS}/forks"
SDK = f"{FORKS}/crc-sdk"
DOCS = f"{FORKS}/crc-docs"
WT = f"{FORKS}/worktrees/crc-sdk-mar-260"
REPO = f"{WS}/parametric-insurance-design"
AGENT_WT = f"{REPO}/.claude/worktrees/agent-a1b2"

CWD_LABELS = {
    SDK: "forks/crc-sdk",
    DOCS: "forks/crc-docs",
    WT: "forks/worktrees/crc-sdk-mar-260",
    FORKS: "forks",
    REPO: "this repo",
    AGENT_WT: "this repo's agent worktree",
    HOME: "~",
}

BODY = "$(cat <<'EOF'\n## Summary\n1) adds the step payout\nEOF\n)"
BODY_MENTIONS_FORK = (
    "$(cat <<'EOF'\n"
    f"Run: cd {SDK} && gh pr create --base parametric\n"
    "1) an unbalanced paren\n"
    "EOF\n"
    ")"
)

# (expected, cwd, command). Exactly as an agent would write them.
CASES: list[tuple[str, str, str]] = [
    # The runbook's prescribed fork commands.
    (
        "allow",
        WT,
        "gh pr create --repo marc272/crc-sdk --base parametric"
        " --head marcprinzing/mar-260-step-payout --draft"
        ' --title "[MAR-260] feat(parametric): add the step payout"',
    ),
    (
        "allow",
        REPO,
        f"cd {WT} && gh pr create --repo marc272/crc-sdk --base parametric"
        " --head marcprinzing/mar-260-step-payout --draft --title t"
        f" --body-file {WT}-notes/pr-body.md",
    ),
    (
        "allow",
        SDK,
        "gh pr create --repo marc272/crc-sdk --base parametric --head x"
        f' --title t --body "{BODY}"',
    ),
    (
        "allow",
        REPO,
        "gh pr merge 12 --repo marc272/crc-sdk --squash"
        ' --subject "feat(parametric): add the step payout (#12)"'
        ' --body "Refs: MAR-260"',
    ),
    ("allow", REPO, "gh pr checks 12 --repo marc272/crc-sdk --watch"),
    ("allow", DOCS, "gh pr checks 7 --repo marc272/crc-docs"),
    ("allow", SDK, "gh pr merge 13 --repo marc272/crc-sdk --merge"),
    (
        "allow",
        SDK,
        "gh pr create --repo marc272/crc-sdk --base parametric"
        " --head sync/upstream-main-2026-11-05"
        ' --title "chore: merge upstream main into parametric"',
    ),
    (
        "allow",
        REPO,
        "gh pr list --repo marc272/crc-docs --state open"
        " --json number,title,headRefName,baseRefName,isDraft,statusCheckRollup",
    ),
    ("allow", SDK, "gh issue list --repo marc272/crc-sdk"),
    (
        "allow",
        REPO,
        f"cd {WT} && gh pr edit 12 --repo marc272/crc-sdk"
        f' --body "$(cat {WT}-notes/pr-body.md)"',
    ),
    (
        "allow",
        SDK,
        "gh pr view $(gh pr list --repo marc272/crc-sdk --json number -q '.[0].number')"
        " --repo marc272/crc-sdk",
    ),
    # Every spelling of the repo flag.
    ("allow", SDK, "gh pr view 3 -R marc272/crc-sdk"),
    ("allow", SDK, "gh pr view 3 -Rmarc272/crc-sdk"),
    ("allow", SDK, "gh pr view 3 -R=marc272/crc-sdk"),
    ("allow", SDK, "gh pr view 3 --repo=marc272/crc-sdk"),
    ("allow", SDK, "gh -R marc272/crc-sdk pr view 3"),
    ("allow", SDK, "gh pr view 3 --repo github.com/marc272/crc-sdk"),
    ("allow", DOCS, "gh pr view 3 --repo https://github.com/marc272/crc-docs"),
    ("allow", SDK, "gh pr view 3 --repo 'marc272/crc-sdk'"),
    # Other gh commands and non-gh commands in a fork path.
    ("allow", SDK, "gh repo set-default --view"),
    ("allow", SDK, "gh api repos/marc272/crc-sdk/pulls"),
    ("allow", SDK, "gh --version"),
    ("allow", SDK, "git status && git log --oneline -3 | cat"),
    ("allow", WT, "uv run pytest -q && uv run mypy"),
    ("allow", SDK, 'git commit -m "docs: explain gh pr create"'),
    ("allow", SDK, 'grep -rn "gh pr" docs/'),
    ("allow", SDK, 'echo "unterminated'),
    ("allow", SDK, "echo $(( 1 << 2 )) && gh pr view 3 --repo marc272/crc-sdk"),
    ("allow", REPO, f"git -C {SDK} fetch origin && git -C {SDK} worktree list"),
    # gh pr and gh issue outside the fork paths.
    ("allow", REPO, "gh pr view 181"),
    ("allow", REPO, "gh pr merge 181 --squash"),
    ("allow", REPO, "gh pr checks 181 --watch && gh pr view 181 --json state"),
    (
        "allow",
        AGENT_WT,
        'gh pr create --draft --title "[MAR-253] x" --body-file results/pr.md',
    ),
    (
        "allow",
        AGENT_WT,
        f'gh pr create --draft --title x --body "{BODY_MENTIONS_FORK}"',
    ),
    ("allow", REPO, f'gh pr comment 181 --body "see {SDK}/AGENTS.md"'),
    ("allow", REPO, f"gh pr list # then cd {SDK}"),
    ("allow", REPO, "cd /tmp && gh pr list"),
    (
        "allow",
        HOME,
        "cd ~/Parametric_Insurance/parametric-insurance-design && gh pr list",
    ),
    ("allow", REPO, "cd ../parametric-insurance-design && gh issue list"),
    # Refused: the command starts in a fork path.
    ("refuse", SDK, "gh pr create --base parametric --head x --draft --title t"),
    ("refuse", WT, "gh pr create --base parametric --head x --draft --title t"),
    ("refuse", DOCS, "gh issue create --title t --body b"),
    ("refuse", SDK, "gh pr status"),
    ("refuse", SDK, "git status | head -5; gh pr view 3"),
    ("refuse", SDK, "gh pr list --repo marc272/crc-sdk && gh pr view 3"),
    ("refuse", SDK, f"cd {REPO} && gh pr list"),
    # Refused: a cd, pushd or popd into a fork path, or one it can't follow.
    ("refuse", REPO, f"cd {SDK} && gh pr create --base parametric --head x"),
    ("refuse", AGENT_WT, f"cd {WT}; gh pr view 3"),
    ("refuse", REPO, f"cd {SDK}\ngh pr list"),
    ("refuse", REPO, "cd ../forks/crc-docs && gh issue list"),
    ("refuse", HOME, "cd ~/Parametric_Insurance/forks/crc-sdk && gh pr list"),
    ("refuse", REPO, 'cd "$HOME/Parametric_Insurance/forks/crc-sdk" && gh pr list'),
    ("refuse", REPO, f"cd {WS}/FORKS/crc-sdk && gh pr list"),
    ("refuse", REPO, f"cd {WS}/fork*/crc-sdk && gh pr list"),
    ("refuse", REPO, 'cd "$WT" && gh pr create --base parametric'),
    ("refuse", REPO, "cd - && gh pr list"),
    ("refuse", REPO, f"pushd {DOCS} && gh issue create --title t"),
    ("refuse", REPO, "popd && gh pr list"),
    ("refuse", REPO, f"(cd {SDK} && gh pr list)"),
    ("refuse", REPO, "(cd /tmp) && cd ../forks/crc-sdk && gh pr list"),
    ("refuse", REPO, f"if cd {SDK}; then gh pr list; fi"),
    ("refuse", REPO, f"gh pr list && cd {SDK}"),
    ("refuse", REPO, f'for d in {FORKS}/*; do (cd "$d" && gh pr list); done'),
    ("refuse", REPO, "- && gh pr list"),
    # Refused: git -C, --git-dir, GIT_DIR, GH_REPO or a path word.
    (
        "refuse",
        REPO,
        f"git -C {SDK} push -u origin x && gh pr create --base parametric --head x",
    ),
    ("refuse", REPO, f"git --git-dir={SDK}/.git log -1 && gh pr list"),
    ("refuse", REPO, 'git -C "$WT" status && gh pr list'),
    ("refuse", REPO, f"GIT_DIR={SDK}/.git gh pr list"),
    ("refuse", REPO, "export GIT_DIR=../forks/crc-sdk/.git; gh pr list"),
    ("refuse", REPO, "GH_REPO=marc272/crc-sdk gh pr list"),
    ("refuse", REPO, "env -C ../forks/crc-sdk gh pr list"),
    # Refused: gh hidden in substitutions, shells, eval and wrappers.
    ("refuse", REPO, f"bash -c 'cd {SDK} && gh pr create --base parametric'"),
    ("refuse", REPO, f'sh -ec "cd {DOCS}; gh issue list"'),
    (
        "refuse",
        REPO,
        f'PR=$(cd {SDK} && gh pr create --base parametric --head x) && echo "$PR"',
    ),
    ("refuse", SDK, "url=$(gh pr create --base parametric --head x --draft)"),
    ("refuse", SDK, "echo `gh pr view 3`"),
    ("refuse", SDK, "diff <(gh pr diff 3) /dev/null"),
    ("refuse", SDK, 'eval "gh pr view 3"'),
    ("refuse", SDK, "timeout 60 gh pr checks 3 --watch"),
    ("refuse", SDK, "echo 3 | xargs gh pr view"),
    ("refuse", SDK, "/opt/homebrew/bin/gh pr view 3"),
    ("refuse", SDK, '"gh" pr view 3'),
    ("refuse", SDK, "g\\h pr view 3"),
    ("refuse", SDK, "=gh pr view 3"),
    ("refuse", REPO, 'nocorrect cd "$WT" && gh pr list'),
    # Refused: a here-document or arithmetic doesn't hide the next lines.
    ("refuse", REPO, f"(( n = 1 << 2 ))\ncd {SDK} && gh pr list"),
    ("refuse", REPO, f"echo $(( 1 << 2 ))\ncd {SDK} && gh pr list"),
    ("refuse", REPO, f"cat <<'EOF'\nnotes\nEOF\ncd {SDK} && gh pr list"),
    # Refused: a repo flag that isn't a literal marc272 repository.
    ("refuse", SDK, "gh pr list --repo RiskThinking/crc-sdk"),
    ("refuse", SDK, 'gh pr list --repo "$REPO"'),
    ("refuse", SDK, "gh pr view 3 --repo=$FORK"),
    ("refuse", SDK, "gh pr list -R marc272/crc-sdk -R RiskThinking/crc-sdk"),
    ("refuse", SDK, "gh pr create --title t -- --repo marc272/crc-sdk"),
    ("refuse", SDK, "gh pr view 3 --repo"),
    ("refuse", SDK, "gh pr view 3 --repo marc272/"),
    ("refuse", SDK, "gh pr view 3 --repo marc272-evil/crc-sdk"),
    # Refused: a command the hook can't parse, in a fork path.
    ("refuse", SDK, 'gh pr create --title "unterminated'),
    ("refuse", REPO, f"cd {SDK} && gh pr list --body 'unterminated"),
    # Refused, by design: gh as a plain word in a fork path.
    ("refuse", SDK, "echo gh pr list"),
    # MAR-261: the other repo-scoped gh commands. Allowed outside the forks,
    # and in them with --repo marc272/<fork>; the runbook's gh api call.
    (
        "allow",
        REPO,
        "gh api repos/marc272/parametric-insurance-design/check-runs/42122091157"
        "/annotations",
    ),
    ("allow", REPO, "gh api 'repos/{owner}/{repo}/pulls' --jq '.[].number'"),
    ("allow", AGENT_WT, "gh run view 42122091157 --log-failed"),
    ("allow", REPO, "gh label list && gh run rerun 42122091157 --failed"),
    (
        "allow",
        SDK,
        "gh label create needs-review --repo marc272/crc-sdk --color ededed",
    ),
    ("allow", DOCS, "gh label clone marc272/crc-sdk -R marc272/crc-docs"),
    ("allow", WT, "gh run rerun 123 --failed --repo marc272/crc-sdk"),
    ("allow", DOCS, "gh run cancel 456 -R marc272/crc-docs"),
    ("allow", SDK, "gh run list --repo marc272/crc-sdk --branch parametric -L 5"),
    ("allow", SDK, "gh secret list --repo marc272/crc-sdk"),
    ("allow", SDK, "gh variable set FOO --body bar --repo marc272/crc-sdk"),
    ("allow", SDK, "gh cache delete --all --repo marc272/crc-sdk"),
    ("allow", SDK, "gh cache list -R marc272/crc-sdk"),
    # gh api in a fork: allowed when the repository is written out, and when
    # {owner}/{repo} only appear where gh doesn't fill them in.
    ("allow", SDK, "gh api user --jq .login"),
    ("allow", SDK, "gh api repos/marc272/crc-sdk/branches/{branch}"),
    ("allow", SDK, "gh api repos/marc272/crc-sdk/pulls --jq '.[].head | {repo}'"),
    (
        "allow",
        SDK,
        "gh api repos/marc272/crc-sdk/issues/3/comments -f body='rename {repo}'",
    ),
    (
        "allow",
        SDK,
        "gh api graphql -F owner=marc272 -F name=crc-sdk -f query='query($owner:"
        "String!,$name:String!){repository(owner:$owner,name:$name){id}}'",
    ),
    # Not checked: gh run as another tool's word, and other gh groups (their
    # writes are denied by the deny rules).
    ("allow", WT, "uv run pytest -q && gh pr checks 3 --repo marc272/crc-sdk"),
    ("allow", SDK, "gh --version && uv run pytest -q"),
    ("allow", SDK, "gh workflow list"),
    ("allow", SDK, "gh --version && uv run 'unterminated"),
    # Refused: label, run, secret, variable and cache without --repo.
    ("refuse", SDK, "gh label create needs-review --color ededed"),
    ("refuse", DOCS, "gh label list"),
    ("refuse", SDK, "gh label clone marc272/crc-docs"),
    ("refuse", WT, "gh run rerun 123 --failed"),
    ("refuse", SDK, "gh run cancel 456"),
    ("refuse", SDK, "gh run delete 456"),
    ("refuse", SDK, "gh run watch 456"),
    ("refuse", SDK, "gh secret set FOO --body bar"),
    ("refuse", SDK, "gh secret delete FOO"),
    ("refuse", SDK, "gh variable set FOO --body bar"),
    ("refuse", DOCS, "gh variable delete FOO"),
    ("refuse", SDK, "gh cache delete --all"),
    ("refuse", SDK, "gh cache list"),
    ("refuse", SDK, 'gh secret list --repo "$FORK"'),
    ("refuse", SDK, "gh run rerun 123 --repo RiskThinking/crc-sdk"),
    ("refuse", REPO, f"cd {WT} && gh run rerun 123 --failed"),
    ("refuse", REPO, f"git -C {SDK} fetch origin && gh label list"),
    ("refuse", REPO, f"bash -c 'cd {DOCS} && gh variable list'"),
    ("refuse", SDK, "gh run rerun 3 --failed 'unterminated"),
    # Refused: gh api with {owner}/{repo} placeholders in a fork path.
    ("refuse", SDK, "gh api repos/{owner}/{repo}/pulls"),
    ("refuse", SDK, "gh api 'repos/{owner}/{repo}/issues/3/comments' -f body=hi"),
    ("refuse", WT, "gh api -X POST repos/{owner}/{repo}/actions/runs/123/rerun"),
    ("refuse", SDK, "gh api --method DELETE 'repos/{owner}/{repo}/actions/caches/1'"),
    ("refuse", SDK, "gh api repos/:owner/:repo/labels -f name=bug"),
    (
        "refuse",
        SDK,
        "gh api graphql -F owner='{owner}' -F name='{repo}' -f query='query($owner:"
        "String!,$name:String!){repository(owner:$owner,name:$name){id}}'",
    ),
    ("refuse", SDK, "gh api -Fname={repo} -f query=x graphql"),
    ("refuse", SDK, "gh api --paginate repos/{owner}/{repo}/issues --jq '.[].number'"),
    ("refuse", SDK, "gh api -- repos/{owner}/{repo}/pulls"),
    ("refuse", REPO, f"cd {SDK} && gh api repos/{{owner}}/{{repo}}/pulls"),
    ("refuse", SDK, "gh api 'repos/{owner}/{repo}/pulls' 'unterminated"),
]


def run_hook(
    python: str,
    payload: object,
    env: dict[str, str],
    raw: str | None = None,
    force_error: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run the hook once, as Claude Code does, and return the finished process.

    Parameters
    ----------
    python
        The interpreter to run the hook with (``-I``, isolated mode).
    payload
        The hook input, sent as JSON on stdin.
    env
        The environment of the hook process.
    raw
        Text to send on stdin instead of ``payload``.
    force_error
        Make the hook's analysis raise, through ``FORCE_INTERNAL_ERROR``.

    Returns
    -------
    subprocess.CompletedProcess
        The finished process, with its stdout and stderr.
    """
    argv = [python, "-I", str(HOOK)]
    if force_error:
        argv = [python, "-I", "-c", FORCE_INTERNAL_ERROR, str(HOOK)]
    return subprocess.run(
        argv,
        input=json.dumps(payload) if raw is None else raw,
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT,
        timeout=30,
        check=False,
    )


def hook_input(cwd: str, tool: str, tool_input: object) -> dict[str, object]:
    """Return a ``PreToolUse`` hook input for a call of ``tool``.

    Parameters
    ----------
    cwd
        The hook input's ``cwd``: the directory Claude is in.
    tool
        The tool name.
    tool_input
        The tool's input.

    Returns
    -------
    dict
        The hook input, shaped like the example in the hooks reference. A
        terminal-tool call also carries ``mcp_server``, as MCP calls do.
    """
    payload: dict[str, object] = {
        "session_id": "check-fork-gh-guard",
        "transcript_path": "/dev/null",
        "cwd": cwd,
        "permission_mode": "auto",
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": tool_input,
        "tool_use_id": "toolu_check",
    }
    if tool.startswith("mcp__"):
        payload["mcp_server"] = {"name": tool.split("__")[1], "source": "sdk"}
    return payload


def bash_input(cwd: str, command: str, tool: str = "Bash") -> dict[str, object]:
    """Return a ``PreToolUse`` hook input for a Bash command.

    Parameters
    ----------
    cwd
        The directory the command starts in.
    command
        The command.
    tool
        The tool name.

    Returns
    -------
    dict
        The hook input, shaped like the example in the hooks reference.
    """
    return hook_input(cwd, tool, {"command": command, "description": "test case"})


def monitor_input(cwd: str, command: str) -> dict[str, object]:
    """Return a ``PreToolUse`` hook input for a Monitor command.

    Parameters
    ----------
    cwd
        The directory the command starts in.
    command
        The command.

    Returns
    -------
    dict
        The hook input, with the Monitor tool's own input.
    """
    tool_input = {"command": command, "description": "test", "timeout_ms": 300000}
    return hook_input(cwd, "Monitor", tool_input)


def terminal_input(
    cwd: str, command: str, tool_cwd: object = None
) -> dict[str, object]:
    """Return a ``PreToolUse`` hook input for a terminal-tool command.

    Parameters
    ----------
    cwd
        The hook input's ``cwd``.
    command
        The command.
    tool_cwd
        The tool's own ``cwd``, or ``None`` to leave it out.

    Returns
    -------
    dict
        The hook input, with the terminal tool's input (``command``, ``cwd``,
        ``title``).
    """
    tool_input: dict[str, object] = {"command": command, "title": "test"}
    if tool_cwd is not None:
        tool_input["cwd"] = tool_cwd
    return hook_input(cwd, TERMINAL_TOOL, tool_input)


def verdict(proc: subprocess.CompletedProcess[str]) -> str:
    """Classify a hook run as ``allow``, ``refuse`` or a malformed result.

    Parameters
    ----------
    proc
        A finished hook process.

    Returns
    -------
    str
        ``allow`` for exit 0 with no output; ``refuse`` for exit 2 with a
        message that names the fix (a ``marc272/`` repository: ``--repo
        marc272/<fork>``, or ``repos/marc272/<fork>`` for gh api) and nothing
        on stdout; otherwise a description of what went wrong.
    """
    if proc.returncode == 0 and not proc.stdout and not proc.stderr:
        return "allow"
    if (
        proc.returncode == 2
        and not proc.stdout
        and "Refused by the fork gh guard" in proc.stderr
        and ("--repo marc272/" in proc.stderr or "repos/marc272/" in proc.stderr)
    ):
        return "refuse"
    return f"exit {proc.returncode}, stdout {proc.stdout!r}, stderr {proc.stderr!r}"


def check_cases(
    python: str, env: dict[str, str]
) -> tuple[list[str], list[str], list[str]]:
    """Run every case in ``CASES``; return the report, failures and results.

    Parameters
    ----------
    python
        The interpreter to run the hook with.
    env
        The environment of the hook process.

    Returns
    -------
    tuple of list of str
        One report line per case, the lines of the failed cases, and the
        result of each case (see ``verdict``).
    """
    lines, failures, results = [], [], []
    for n, (expected, cwd, command) in enumerate(CASES, 1):
        got = verdict(run_hook(python, bash_input(cwd, command), env))
        results.append(got)
        shown = command.replace("\n", "\\n")
        line = f"{n:3d} [{expected}] {CWD_LABELS.get(cwd, cwd)}: {shown}"
        if got == expected:
            lines.append(f"ok   {line}")
        else:
            lines.append(f"FAIL {line}\n     got: {got}")
            failures.append(line)
    return lines, failures, results


def input_cases() -> list[tuple[str, str, object, str | None, bool]]:
    """Return the cases for other tools, bad input and internal errors.

    Returns
    -------
    list of tuple
        ``(expected, label, payload, raw stdin or None, force an internal
        error)``. A failure of the hook refuses a command that mentions gh
        with a checked subcommand, without parsing it, and lets the rest
        through. The terminal-tool cases run with ``CLAUDE_PROJECT_DIR`` set
        to this repository's main checkout (``REPO``).
    """
    no_cwd = bash_input(SDK, "gh pr list")
    del no_cwd["cwd"]
    gh_elsewhere = {"tool_name": "Bash", "tool_input": {"cmd": "gh issue create"}}
    ws_watch = hook_input(
        SDK,
        "Monitor",
        {
            "ws": {"url": "wss://events.example.com/stream"},
            "description": "gh pr events",
            "timeout_ms": 300000,
        },
    )
    monitor_empty = hook_input(
        SDK, "Monitor", {"description": "gh pr checks", "timeout_ms": 1000}
    )
    poll = (
        "while true; do gh api 'repos/{owner}/{repo}/issues/3/comments'"
        " --jq '.[].body'; sleep 30; done"
    )
    return [
        # Monitor: its command runs in the same shell environment as Bash.
        (
            "refuse",
            "Monitor, forks/crc-sdk: gh pr checks 3 --watch",
            monitor_input(SDK, "gh pr checks 3 --watch"),
            None,
            False,
        ),
        (
            "allow",
            "Monitor, forks/crc-sdk: gh pr checks 3 --repo marc272/crc-sdk --watch",
            monitor_input(SDK, "gh pr checks 3 --repo marc272/crc-sdk --watch"),
            None,
            False,
        ),
        (
            "refuse",
            "Monitor, forks/crc-sdk: a gh api poll loop with {owner}/{repo}",
            monitor_input(SDK, poll),
            None,
            False,
        ),
        (
            "refuse",
            "Monitor, this repo: cd forks/worktrees/crc-sdk-mar-260 && gh run watch 9",
            monitor_input(REPO, f"cd {WT} && gh run watch 9"),
            None,
            False,
        ),
        (
            "allow",
            "Monitor, forks/crc-sdk: tail -f a log",
            monitor_input(SDK, "tail -f results/run.log | grep --line-buffered ERROR"),
            None,
            False,
        ),
        (
            "allow",
            "Monitor, this repo: gh pr checks 3 --watch",
            monitor_input(REPO, "gh pr checks 3 --watch"),
            None,
            False,
        ),
        (
            "allow",
            "Monitor WebSocket watch (no command; description says gh pr)",
            ws_watch,
            None,
            False,
        ),
        (
            "refuse",
            "Monitor with neither command nor ws, gh pr in the input",
            monitor_empty,
            None,
            False,
        ),
        # The terminal tool: its own cwd, else the session's working directory.
        (
            "refuse",
            "terminal tool, cwd forks/crc-sdk: gh pr list",
            terminal_input(REPO, "gh pr list", SDK),
            None,
            False,
        ),
        (
            "refuse",
            "terminal tool, cwd ~/Parametric_Insurance/forks/crc-docs: gh issue list",
            terminal_input(
                REPO, "gh issue list", "~/Parametric_Insurance/forks/crc-docs"
            ),
            None,
            False,
        ),
        (
            "refuse",
            "terminal tool, cwd ../forks/crc-sdk (project dir): gh run rerun 3",
            terminal_input(AGENT_WT, "gh run rerun 3", "../forks/crc-sdk"),
            None,
            False,
        ),
        (
            "refuse",
            "terminal tool, no cwd, Claude in forks/crc-sdk: gh pr list",
            terminal_input(SDK, "gh pr list"),
            None,
            False,
        ),
        (
            "refuse",
            "terminal tool, no cwd: cd forks/worktrees/crc-sdk-mar-260 && gh pr create",
            terminal_input(REPO, f"cd {WT} && gh pr create --base parametric"),
            None,
            False,
        ),
        (
            "refuse",
            "terminal tool, cwd forks/crc-sdk: gh api repos/{owner}/{repo}/pulls",
            terminal_input(REPO, "gh api repos/{owner}/{repo}/pulls", SDK),
            None,
            False,
        ),
        (
            "allow",
            "terminal tool, cwd forks/crc-sdk: gh pr list --repo marc272/crc-sdk",
            terminal_input(REPO, "gh pr list --repo marc272/crc-sdk", SDK),
            None,
            False,
        ),
        (
            "allow",
            "terminal tool, cwd this repo, Claude in forks/crc-sdk: gh pr list",
            terminal_input(SDK, "gh pr list", REPO),
            None,
            False,
        ),
        (
            "allow",
            "terminal tool, no cwd, this repo: gh pr list",
            terminal_input(REPO, "gh pr list"),
            None,
            False,
        ),
        (
            "allow",
            "terminal tool, cwd forks/worktrees/crc-sdk-mar-260: uv run pytest -q",
            terminal_input(REPO, "uv run pytest -q", WT),
            None,
            False,
        ),
        (
            "refuse",
            "terminal tool, cwd not a string: gh pr list --repo marc272/crc-sdk",
            terminal_input(REPO, "gh pr list --repo marc272/crc-sdk", 3),
            None,
            False,
        ),
        (
            "allow",
            "terminal tool, cwd not a string: ls",
            terminal_input(REPO, "ls", 3),
            None,
            False,
        ),
        (
            "allow",
            "another MCP tool with a command, forks/crc-sdk: gh pr list",
            hook_input(SDK, "mcp__other__run", {"command": "gh pr list"}),
            None,
            False,
        ),
        (
            "allow",
            "another tool (Edit)",
            bash_input(SDK, "gh pr x", "Edit"),
            None,
            False,
        ),
        ("allow", "no cwd: the process cwd, this checkout", no_cwd, None, False),
        ("allow", "stdin that isn't JSON", None, "not json", False),
        ("refuse", "stdin that isn't JSON, with gh pr", None, "gh pr create", False),
        ("allow", "a JSON array", [], None, False),
        ("refuse", "a JSON array with gh pr", ["gh pr create"], None, False),
        ("allow", "no tool_input.command", {"tool_name": "Bash"}, None, False),
        (
            "refuse",
            "no tool_input.command, gh issue elsewhere",
            gh_elsewhere,
            None,
            False,
        ),
        (
            "refuse",
            "internal error: gh pr list, this repo",
            bash_input(REPO, "gh pr list"),
            None,
            True,
        ),
        (
            "refuse",
            "internal error: gh issue list --repo marc272/crc-sdk (not parsed)",
            bash_input(SDK, "gh issue list --repo marc272/crc-sdk"),
            None,
            True,
        ),
        (
            "allow",
            "internal error: ls -la, a fork",
            bash_input(SDK, "ls -la"),
            None,
            True,
        ),
        (
            "allow",
            "internal error: git push, a fork",
            bash_input(SDK, "git push"),
            None,
            True,
        ),
        (
            "refuse",
            "internal error: gh run rerun 3, a fork",
            bash_input(SDK, "gh run rerun 3"),
            None,
            True,
        ),
        (
            "refuse",
            "internal error: Monitor gh api repos/{owner}/{repo}/pulls, a fork",
            monitor_input(SDK, "gh api repos/{owner}/{repo}/pulls"),
            None,
            True,
        ),
        (
            "refuse",
            "internal error: terminal tool gh label list, cwd a fork",
            terminal_input(REPO, "gh label list", SDK),
            None,
            True,
        ),
        (
            "allow",
            "internal error: gh --version && uv run pytest -q, a fork",
            bash_input(SDK, "gh --version && uv run pytest -q"),
            None,
            True,
        ),
    ]


def check_inputs(
    python: str, env: dict[str, str]
) -> tuple[list[str], list[str], list[str]]:
    """Run the cases of ``input_cases``; return the report, failures, results.

    Parameters
    ----------
    python
        The interpreter to run the hook with.
    env
        The environment of the hook process.

    Returns
    -------
    tuple of list of str
        One report line per case, the lines of the failed cases, and the
        result of each case (see ``verdict``).
    """
    lines, failures, results = [], [], []
    for expected, label, payload, raw, force_error in input_cases():
        proc = run_hook(python, payload, env, raw=raw, force_error=force_error)
        got = verdict(proc)
        results.append(got)
        line = f"    [{expected}] {label}"
        if got == expected:
            lines.append(f"ok   {line}")
        else:
            lines.append(f"FAIL {line}\n     got: {got}")
            failures.append(line)
    return lines, failures, results


def hook_key_problems(settings: dict[str, object]) -> list[str]:
    """Return the hook entries of a settings object with keys the schema lacks.

    Parameters
    ----------
    settings
        A parsed settings file.

    Returns
    -------
    list of str
        One line per matcher group or command hook with a key outside
        ``HOOK_MATCHER_KEYS`` or ``HOOK_COMMAND_KEYS``.
    """
    problems = []
    events = settings.get("hooks") or {}
    if not isinstance(events, dict):
        return ["settings.json: hooks is not an object"]
    for event, groups in events.items():
        for group in groups if isinstance(groups, list) else []:
            extra = sorted(set(group) - HOOK_MATCHER_KEYS)
            if extra:
                problems.append(
                    f"{event} matcher group: keys not in the schema {extra}"
                )
            for hook in group.get("hooks", []):
                if hook.get("type") != "command":
                    continue
                extra = sorted(set(hook) - HOOK_COMMAND_KEYS)
                if extra:
                    problems.append(
                        f"{event} command hook: keys not in the schema {extra}"
                    )
    return problems


def matcher_names(matcher: str) -> set[str] | None:
    """Return the tool names an exact-match hook matcher lists.

    Parameters
    ----------
    matcher
        A hook matcher.

    Returns
    -------
    set of str or None
        The names separated by ``|`` or ``,``, or ``None`` if the hooks
        reference reads the matcher as a regular expression.
    """
    if not EXACT_MATCHER.fullmatch(matcher):
        return None
    return {name.strip() for name in re.split(r"[|,]", matcher) if name.strip()}


def check_settings(env: dict[str, str]) -> list[str]:
    """Check the hook's wiring in ``.claude/settings.json``; return failures.

    The guard must be one ``PreToolUse`` hook whose matcher is a list of exact
    tool names that includes ``GUARDED_TOOLS``, and the terminal tool must be
    denied. The hook's command string runs through ``sh -c`` with
    ``CLAUDE_PROJECT_DIR`` set to this checkout, as Claude Code runs it, for
    Bash, Monitor and terminal-tool commands it must refuse or allow.

    Parameters
    ----------
    env
        The environment of the hook process.

    Returns
    -------
    list of str
        A description of each check that failed.
    """
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    failures = hook_key_problems(settings)
    probe: dict[str, object] = {
        "hooks": {"PreToolUse": [{"hooks": [{**HOOK_PROBE, "onFailure": "block"}]}]}
    }
    if not hook_key_problems(probe):
        failures.append("the schema key check doesn't fire on onFailure")
    if matcher_names("mcp__terminal__.*") is not None:
        failures.append("the matcher check doesn't read .* as a regular expression")
    deny = settings.get("permissions", {}).get("deny") or []
    if not deny:
        failures.append("settings.json lost its permissions.deny rules")
    for rule in (*GH_REPO_DENY_RULES, TERMINAL_TOOL):
        if rule not in deny:
            failures.append(f"settings.json lacks the deny rule {rule}")
    found = [
        (str(group.get("matcher", "")), hook)
        for group in settings.get("hooks", {}).get("PreToolUse", [])
        for hook in group.get("hooks", [])
        if "fork_gh_guard.py" in str(hook.get("command", ""))
    ]
    if len(found) != 1:
        return [*failures, f"want 1 PreToolUse hook on the guard: {len(found)}"]
    matcher, hook = found[0]
    names = matcher_names(matcher)
    if names is None:
        failures.append(f"the guard's matcher {matcher!r} is a regular expression")
    else:
        missing = [tool for tool in GUARDED_TOOLS if tool not in names]
        if missing:
            failures.append(f"the guard's matcher {matcher!r} lacks {missing}")
    command = str(hook["command"])
    if hook.get("type") != "command" or "args" in hook:
        failures.append("the hook must be a shell-form command hook (no args)")
    if not command.startswith("python3 -I ") or "$CLAUDE_PROJECT_DIR" not in command:
        failures.append(f"unexpected hook command: {command}")
    if not isinstance(hook.get("timeout"), (int, float)):
        failures.append("the hook must set a timeout")
    sh_env = {**env, "CLAUDE_PROJECT_DIR": str(ROOT)}
    for expected, payload in (
        ("refuse", bash_input(REPO, f"cd {SDK} && gh pr create --base parametric")),
        ("allow", bash_input(SDK, "gh pr checks 3 --repo marc272/crc-sdk")),
        ("refuse", monitor_input(SDK, "gh run watch 3")),
        ("refuse", terminal_input(REPO, "gh pr list", SDK)),
        ("allow", terminal_input(REPO, "gh pr list --repo marc272/crc-sdk", SDK)),
    ):
        proc = subprocess.run(
            ["sh", "-c", command],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=sh_env,
            cwd=ROOT,
            timeout=30,
            check=False,
        )
        got = verdict(proc)
        if got != expected:
            shown = f"{payload['tool_name']} {payload['tool_input']!r}"
            failures.append(f"settings command on {shown}: want {expected}, {got}")
    return failures


def check_grammar() -> list[str]:
    """Check that the hook parses with Python 3.9's grammar; return failures.

    Returns
    -------
    list of str
        The syntax error, if any.
    """
    try:
        ast.parse(HOOK.read_text(encoding="utf-8"), feature_version=(3, 9))
    except SyntaxError as exc:
        return [f"the hook needs a Python newer than 3.9: {exc}"]
    return []


def markdown_table(results: list[str]) -> str:
    """Return the cases and their results as a Markdown table, for the PR body.

    In commands, ``<WS>`` stands for the workspace folder ``WS``.

    Parameters
    ----------
    results
        The result of each case, in the order of ``CASES``.

    Returns
    -------
    str
        A table with the number, starting directory, command, expectation and
        result of each case.
    """

    def code(text: str) -> str:
        text = text.replace(WS, "<WS>").replace("\n", "\\n").replace("|", "\\|")
        return f"`` {text} ``" if "`" in text else f"`{text}`"

    rows = [
        "| # | Starts in | Command | Expected | Result |",
        "|---|---|---|---|---|",
    ]
    pairs = zip(CASES, results, strict=True)
    for n, ((expected, cwd, command), got) in enumerate(pairs, 1):
        label = CWD_LABELS.get(cwd, cwd)
        result = f"**{got}**" if got == expected else f"FAIL: {got}"
        rows.append(f"| {n} | {label} | {code(command)} | {expected} | {result} |")
    return "\n".join(rows)


def markdown_input_table(results: list[str]) -> str:
    """Return the cases of ``input_cases`` and their results as a table.

    Parameters
    ----------
    results
        The result of each case, in the order of ``input_cases()``.

    Returns
    -------
    str
        A table with the label, expectation and result of each case.
    """
    rows = ["| Hook input | Expected | Result |", "|---|---|---|"]
    pairs = zip(input_cases(), results, strict=True)
    for (expected, label, *_), got in pairs:
        result = f"**{got}**" if got == expected else f"FAIL: {got}"
        rows.append(f"| {label} | {expected} | {result} |")
    return "\n".join(rows)


def main() -> int:
    """Run all checks and print a report.

    Returns
    -------
    int
        0 if every check passes, 1 otherwise.
    """
    parser = argparse.ArgumentParser(
        description="Test the fork gh guard hook (MAR-253)."
    )
    parser.add_argument(
        "--python", default=sys.executable, help="interpreter for the hook"
    )
    parser.add_argument(
        "--markdown", action="store_true", help="also print the cases as a table"
    )
    args = parser.parse_args()
    # Claude Code sets CLAUDE_PROJECT_DIR for hooks: the main checkout, which
    # the terminal tool's relative cwd may be resolved against.
    env = {**os.environ, "HOME": HOME, "CLAUDE_PROJECT_DIR": REPO}

    started = time.monotonic()
    lines, failures, results = check_cases(args.python, env)
    elapsed = time.monotonic() - started
    print("\n".join(lines))
    input_lines, input_failures, input_results = check_inputs(args.python, env)
    print("\n".join(input_lines))
    failures += input_failures
    for problem in check_settings(env) + check_grammar():
        print(f"FAIL {problem}")
        failures.append(problem)
    if args.markdown:
        print()
        print(markdown_table(results))
        print()
        print(markdown_input_table(input_results))
    version = subprocess.run(
        [args.python, "--version"], capture_output=True, text=True, check=False
    ).stdout.strip()
    per_case = 1000 * elapsed / len(CASES)
    print(
        f"check_fork_gh_guard: {len(CASES)} cases on {version},"
        f" {per_case:.0f} ms per hook call"
    )
    if failures:
        print(f"check_fork_gh_guard: FAILED, {len(failures)} problem(s) (see above)")
        return 1
    print("check_fork_gh_guard: all cases and checks as expected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
