#!/usr/bin/env python3
"""Test the fork gh guard hook, ``.claude/hooks/fork_gh_guard.py`` (MAR-253).

The hook refuses a ``gh pr`` or ``gh issue`` command that may run in a CRC
fork path without ``--repo marc272/<fork>``. This script runs it the way
Claude Code does, one process per case with the ``PreToolUse`` JSON on stdin,
and checks the exit status: 0 allows with no output, 2 refuses with a message
on stderr that says how to fix the command. It also checks that:

- ``.claude/settings.json`` wires the hook as a ``PreToolUse`` hook on Bash,
  by running its command string through ``sh -c`` with ``CLAUDE_PROJECT_DIR``
  set, as Claude Code does, and keeps its deny rules;
- the hook parses with Python 3.9's grammar, the oldest ``python3`` it may get
  (macOS's ``/usr/bin/python3``);
- bad input (not JSON, no command) is refused and other tools pass.

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
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / ".claude" / "hooks" / "fork_gh_guard.py"
SETTINGS = ROOT / ".claude" / "settings.json"

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
]


def run_hook(
    python: str, payload: object, env: dict[str, str], raw: str | None = None
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

    Returns
    -------
    subprocess.CompletedProcess
        The finished process, with its stdout and stderr.
    """
    return subprocess.run(
        [python, "-I", str(HOOK)],
        input=json.dumps(payload) if raw is None else raw,
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT,
        timeout=30,
        check=False,
    )


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
    return {
        "session_id": "check-fork-gh-guard",
        "transcript_path": "/dev/null",
        "cwd": cwd,
        "permission_mode": "auto",
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": {"command": command, "description": "test case"},
        "tool_use_id": "toolu_check",
    }


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
        message that names the fix and nothing on stdout; otherwise a
        description of what went wrong.
    """
    if proc.returncode == 0 and not proc.stdout and not proc.stderr:
        return "allow"
    if (
        proc.returncode == 2
        and not proc.stdout
        and "Refused by the fork gh guard" in proc.stderr
        and "--repo marc272/" in proc.stderr
    ):
        return "refuse"
    return f"exit {proc.returncode}, stdout {proc.stdout!r}, stderr {proc.stderr!r}"


def check_cases(python: str, env: dict[str, str]) -> tuple[list[str], list[str]]:
    """Run every case in ``CASES``; return the report lines and the failures.

    Parameters
    ----------
    python
        The interpreter to run the hook with.
    env
        The environment of the hook process.

    Returns
    -------
    tuple of list of str
        One report line per case, and the lines of the failed cases.
    """
    lines, failures = [], []
    for n, (expected, cwd, command) in enumerate(CASES, 1):
        got = verdict(run_hook(python, bash_input(cwd, command), env))
        shown = command.replace("\n", "\\n")
        line = f"{n:3d} [{expected}] {CWD_LABELS.get(cwd, cwd)}: {shown}"
        if got == expected:
            lines.append(f"ok   {line}")
        else:
            lines.append(f"FAIL {line}\n     got: {got}")
            failures.append(line)
    return lines, failures


def check_inputs(python: str, env: dict[str, str]) -> list[str]:
    """Check bad hook input and other tools; return the failures.

    Parameters
    ----------
    python
        The interpreter to run the hook with.
    env
        The environment of the hook process.

    Returns
    -------
    list of str
        A description of each check that failed.
    """
    failures = []
    edit = bash_input(SDK, "gh pr create --base parametric", tool="Edit")
    if verdict(run_hook(python, edit, env)) != "allow":
        failures.append("a tool other than Bash is not allowed")
    for label, payload, raw in (
        ("stdin that is not JSON", None, "not json"),
        ("a JSON array", [], None),
        ("no tool_input.command", {"tool_name": "Bash", "cwd": SDK}, None),
    ):
        proc = run_hook(python, payload, env, raw=raw)
        if proc.returncode != 2 or "fork gh guard" not in proc.stderr:
            failures.append(f"{label} is not refused (exit {proc.returncode})")
    no_cwd = bash_input(SDK, "gh pr list")
    del no_cwd["cwd"]
    if verdict(run_hook(python, no_cwd, env)) != "allow":
        failures.append("an input without cwd isn't checked in the process cwd")
    return failures


def check_settings(env: dict[str, str]) -> list[str]:
    """Check the hook's wiring in ``.claude/settings.json``; return failures.

    The hook's command string runs through ``sh -c`` with
    ``CLAUDE_PROJECT_DIR`` set to this checkout, as Claude Code runs it, once
    for a command it must refuse and once for one it must allow.

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
    failures = []
    if not settings.get("permissions", {}).get("deny"):
        failures.append("settings.json lost its permissions.deny rules")
    hooks = [
        hook
        for group in settings.get("hooks", {}).get("PreToolUse", [])
        if group.get("matcher") == "Bash"
        for hook in group.get("hooks", [])
        if "fork_gh_guard.py" in str(hook.get("command", ""))
    ]
    if len(hooks) != 1:
        return [*failures, f"want 1 PreToolUse Bash hook on the guard: {len(hooks)}"]
    hook = hooks[0]
    command = str(hook["command"])
    if hook.get("type") != "command" or "args" in hook:
        failures.append("the hook must be a shell-form command hook (no args)")
    if not command.startswith("python3 -I ") or "$CLAUDE_PROJECT_DIR" not in command:
        failures.append(f"unexpected hook command: {command}")
    if hook.get("onFailure") != "block":
        failures.append('the hook must set "onFailure": "block"')
    sh_env = {**env, "CLAUDE_PROJECT_DIR": str(ROOT)}
    for expected, cwd, bash in (
        ("refuse", REPO, f"cd {SDK} && gh pr create --base parametric"),
        ("allow", SDK, "gh pr checks 3 --repo marc272/crc-sdk"),
    ):
        proc = subprocess.run(
            ["sh", "-c", command],
            input=json.dumps(bash_input(cwd, bash)),
            capture_output=True,
            text=True,
            env=sh_env,
            cwd=ROOT,
            timeout=30,
            check=False,
        )
        got = verdict(proc)
        if got != expected:
            failures.append(f"settings command on {bash!r}: want {expected}, {got}")
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


def markdown_table() -> str:
    """Return the cases as a Markdown table, for the PR body.

    Returns
    -------
    str
        A table with the number, starting directory, command and expectation.
    """

    def code(text: str) -> str:
        text = text.replace("\n", "\\n").replace("|", "\\|")
        return f"`` {text} ``" if "`" in text else f"`{text}`"

    rows = ["| # | Starts in | Command | Expected |", "|---|---|---|---|"]
    for n, (expected, cwd, command) in enumerate(CASES, 1):
        label = CWD_LABELS.get(cwd, cwd)
        rows.append(f"| {n} | {label} | {code(command)} | {expected} |")
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
    env = {**os.environ, "HOME": HOME}

    started = time.monotonic()
    lines, failures = check_cases(args.python, env)
    elapsed = time.monotonic() - started
    print("\n".join(lines))
    for problem in check_inputs(args.python, env) + check_settings(env):
        print(f"FAIL {problem}")
        failures.append(problem)
    for problem in check_grammar():
        print(f"FAIL {problem}")
        failures.append(problem)
    if args.markdown:
        print()
        print(markdown_table())
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
