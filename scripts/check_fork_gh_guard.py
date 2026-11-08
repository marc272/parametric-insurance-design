#!/usr/bin/env python3
"""Test the guard hooks in ``.claude/hooks/`` (MAR-253, MAR-289).

The fork gh guard, ``fork_gh_guard.py``, refuses a repo-scoped ``gh`` command
(``gh pr``, ``issue``, ``release``, ``workflow`` and the other groups of its
``REPO_FLAG_SUBCOMMANDS``) that may run in a CRC fork path without
``--repo marc272/<fork>``, and a ``gh api`` call there that uses the
``{owner}``/``{repo}`` placeholders (MAR-261). Wherever it runs, it refuses
the gh commands that the deny rules deny, in every spelling (MAR-263), and
git commands that make or push tags (MAR-289). The session guard,
``session_guard.py``, refuses a ``start_session`` that would run somewhere
else, and fails closed on bad input (``SESSION_CASES``, MAR-289). This
script runs them the way Claude Code does, one process per case with the
``PreToolUse`` JSON on stdin, and checks the exit status: 0 allows with no
output, 2 refuses with a message on stderr that says what to do. It also
checks that:

- the Bash deny rules of ``.claude/settings.json`` deny the ``gh -R <repo>
  <group>`` forms and other spellings of the denied gh writes, and don't deny
  the runbook's prescribed commands (``RULE_CASES``, MAR-263, MAR-282). Rules
  load at session start, so they are matched here the way the permissions
  page says Claude Code matches them (``rule_matches``, ``denied_by``), a
  model checked against the page's own examples (``DOC_RULE_EXAMPLES``);
- its other deny rules remove the app tools that Marc decided to deny and
  keep the rest (``TOOL_RULE_CASES``, MAR-282), by a model of tool-name
  matching checked against the page (``tool_rule_matches``,
  ``TOOL_RULE_DOC_EXAMPLES``), and every one is a bare ``mcp__`` name, the
  only form settings accept for MCP tools (``tool_rule_problems``);
- ``.claude/settings.json`` wires the hook as one ``PreToolUse`` hook whose
  matcher names Bash, Monitor and the terminal tool, by running its command
  string through ``sh -c`` with ``CLAUDE_PROJECT_DIR`` set, as Claude Code
  does; that it keeps its deny rules; and that it denies the terminal tool;
  and the same for the session guard, on the one tool ``start_session``;
- the hooks parse with Python 3.9's grammar, the oldest ``python3`` they may
  get (macOS's ``/usr/bin/python3``);
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
SESSION_HOOK = ROOT / ".claude" / "hooks" / "session_guard.py"
SESSION_TOOL = "mcp__ccd_session__start_session"
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
# The app tools that start processes or move the session, denied by Marc's
# decision on MAR-263's survey (MAR-282). The preview_start rule is lifted
# when the website work resumes (docs/ORCHESTRATION.md, "One-time setup").
APP_TOOL_DENY_RULES = (
    "mcp__Claude_Browser__preview_start",
    "mcp__Claude_Code_iOS_Simulator__*",
    "mcp__ccd_directory__change_directory",
    "mcp__computer-use__*",
)
# The routes to a GitHub merge or approval that start no process, denied by
# Marc's decision on MAR-282 (MAR-289).
MERGE_ROUTE_DENY_RULES = (
    "mcp__*__set_auto_merge",
    "mcp__*__merge_diff",
    "mcp__*__submit_diff_review",
    "mcp__claude-in-chrome__*",
    "mcp__plugin_engineering_github__*",
)
# The Linear connector in this session's tool list; its server name is the
# connector's id, which is why the rules above use a glob.
LINEAR = "mcp__ccb629fc-2d2f-483b-990d-6d59dd8fda30"
# The hook says this of a denied gh command (MAR-263), and only of one.
DENIED_MARK = "is denied in every spelling"
# The session guard's own marks (MAR-289).
SESSION_REFUSED = "Refused by the session guard"
SESSION_WOULD_MOVE = "would run somewhere else"
SESSION_MALFORMED = "couldn't check this start_session call"
# The hooks reference, "Matcher patterns": a matcher of only these characters
# is an exact tool name, or a list of them separated by | or ,; any other
# character makes it an unanchored JavaScript regular expression.
EXACT_MATCHER = re.compile(r"[A-Za-z0-9_\-, |]*")

# Loads a hook as a module, makes its analysis raise (evaluate() in the fork gh
# guard, check() in the session guard), and runs main(), so that main's
# handling of an internal error runs in a real hook process.
FORCE_INTERNAL_ERROR = """\
import importlib.util, sys
spec = importlib.util.spec_from_file_location("guard_under_test", sys.argv[1])
hook = importlib.util.module_from_spec(spec)
sys.modules["guard_under_test"] = hook
spec.loader.exec_module(hook)
def broken(*args, **kwargs):
    raise RuntimeError("forced by check_fork_gh_guard")
hook.evaluate = hook.check = broken
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
    # Refused: a repo flag that isn't a literal marc272 repository. A
    # RiskThinking one is denied wherever it runs (MAR-263: "deny").
    ("deny", SDK, "gh pr list --repo RiskThinking/crc-sdk"),
    ("refuse", SDK, 'gh pr list --repo "$REPO"'),
    ("refuse", SDK, "gh pr view 3 --repo=$FORK"),
    ("deny", SDK, "gh pr list -R marc272/crc-sdk -R RiskThinking/crc-sdk"),
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
    # MAR-282: a rerun of a fork's run is denied (allowed until then).
    ("deny", WT, "gh run rerun 123 --failed --repo marc272/crc-sdk"),
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
    # Not checked: gh run as another tool's word. Case 121 was allowed until
    # MAR-263, which checks gh workflow in fork paths: it is refused now.
    ("allow", WT, "uv run pytest -q && gh pr checks 3 --repo marc272/crc-sdk"),
    ("allow", SDK, "gh --version && uv run pytest -q"),
    ("refuse", SDK, "gh workflow list"),
    ("allow", SDK, "gh --version && uv run 'unterminated"),
    # Refused: label, run, secret, variable and cache without --repo.
    ("refuse", SDK, "gh label create needs-review --color ededed"),
    ("refuse", DOCS, "gh label list"),
    ("refuse", SDK, "gh label clone marc272/crc-docs"),
    ("deny", WT, "gh run rerun 123 --failed"),  # MAR-282: refused until then
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
    ("deny", SDK, "gh run rerun 123 --repo RiskThinking/crc-sdk"),
    ("deny", REPO, f"cd {WT} && gh run rerun 123 --failed"),  # MAR-282
    ("refuse", REPO, f"git -C {SDK} fetch origin && gh label list"),
    ("refuse", REPO, f"bash -c 'cd {DOCS} && gh variable list'"),
    ("refuse", SDK, "gh run rerun 3 --failed 'unterminated"),
    # Refused: gh api with {owner}/{repo} placeholders in a fork path.
    ("refuse", SDK, "gh api repos/{owner}/{repo}/pulls"),
    ("refuse", SDK, "gh api 'repos/{owner}/{repo}/issues/3/comments' -f body=hi"),
    # MAR-282: a rerun endpoint in a fork path is denied (refused until then).
    ("deny", WT, "gh api -X POST repos/{owner}/{repo}/actions/runs/123/rerun"),
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
    # MAR-263: every gh group with a group-level -R is checked in fork paths:
    # browse, co, discussion, release, ruleset and workflow too.
    ("allow", SDK, "gh workflow list --repo marc272/crc-sdk"),
    ("allow", SDK, "gh -R marc272/crc-sdk workflow view release.yaml"),
    ("allow", SDK, "gh release list -R marc272/crc-sdk"),
    ("allow", DOCS, "gh browse -n --repo marc272/crc-docs"),
    ("allow", SDK, "gh run list -R marc272/crc-sdk --workflow release.yaml"),
    ("allow", REPO, "gh workflow list && gh release list && gh browse -n"),
    (
        "allow",
        REPO,
        "gh release download v1.6.40 -R quarto-dev/quarto-cli"
        " -p 'quarto-1.6.40-macos.tar.gz' -p 'quarto-1.6.40-checksums.txt'",
    ),
    ("refuse", SDK, "gh workflow view release.yaml"),
    ("refuse", SDK, "gh release list"),
    ("refuse", SDK, "gh release view v1.0.0 --json createdAt"),
    ("refuse", DOCS, "gh browse -n"),
    ("refuse", SDK, "gh browse --settings"),
    ("refuse", SDK, "gh discussion list"),
    ("refuse", SDK, "gh ruleset list"),
    ("refuse", SDK, "gh co 3"),
    ("refuse", REPO, f"cd {SDK} && gh release list"),
    ("refuse", SDK, "gh release download v1 -R quarto-dev/quarto-cli"),
    ("refuse", SDK, "gh release list 'unterminated"),
    # MAR-263: the denied gh commands, refused wherever they run and whatever
    # --repo says: the issue's three gh -R forms, every repo flag spelling and
    # position, the aliases, and gh by path, in quotes or in sh -c.
    ("deny", REPO, "gh -R marc272/crc-sdk workflow run release.yaml"),
    ("deny", REPO, "gh -R marc272/crc-sdk release create v1"),
    ("deny", REPO, "gh -R marc272/crc-sdk pr merge 3 --admin"),
    ("deny", SDK, "gh -R marc272/crc-sdk release create v1"),
    ("deny", REPO, "gh --repo marc272/crc-sdk release upload v1 dist/a.whl"),
    ("deny", REPO, "gh --repo=marc272/crc-sdk workflow enable release.yaml"),
    ("deny", REPO, "gh -Rmarc272/crc-sdk release delete v1 --yes"),
    ("deny", REPO, "gh -R=marc272/crc-sdk workflow disable ci.yml"),
    ("deny", REPO, "gh release -R marc272/crc-sdk create v1"),
    ("deny", REPO, "gh workflow --repo marc272/crc-sdk run release.yaml"),
    ("deny", REPO, "gh pr -R marc272/crc-sdk merge 3 --squash --admin"),
    ("deny", REPO, "gh -R marc272/crc-sdk release -R marc272/crc-sdk create v1"),
    ("deny", REPO, "gh release new v1.2.3"),
    ("deny", REPO, "gh release edit v1 --draft=false"),
    ("deny", REPO, "gh release delete-asset v1 a.whl"),
    ("deny", REPO, "gh repo new crc-scratch --public"),
    ("deny", REPO, "gh repo delete marc272/crc-docs --yes"),
    ("deny", REPO, "gh pr merge 3 --admin=true"),
    ("deny", REPO, "gh pr merge --admin 3"),
    ("deny", REPO, "/opt/homebrew/bin/gh release create v1"),
    ("deny", REPO, '"gh" -R marc272/crc-sdk workflow run release.yaml'),
    ("deny", REPO, "bash -c 'gh -R marc272/crc-sdk release new v1'"),
    ("deny", REPO, "timeout 60 gh -R marc272/crc-sdk workflow run release.yaml"),
    ("deny", REPO, "echo v1 | xargs -n1 gh release create"),
    ("deny", REPO, "gh -R RiskThinking/crc-sdk pr create --title t --body b"),
    ("deny", REPO, "gh --repo RiskThinking/crc-sdk issue create --title t"),
    ("deny", REPO, "gh pr create -RRiskThinking/crc-sdk --title t"),
    ("deny", REPO, "gh pr list -R RISKTHINKING/crc-sdk"),
    ("deny", REPO, "gh repo view riskThinking/crc-sdk"),
    ("deny", REPO, "gh api orgs/RISKTHINKING/repos"),
    (
        "deny",
        REPO,
        "gh pr comment 3 --repo marc272/crc-sdk"
        ' --body "port of RiskThinking/crc-sdk#12"',
    ),
    ("deny", REPO, "gh -R marc272/crc-sdk release create v1 --notes 'unterminated"),
    ("deny", REPO, "gh repo new x --description 'unterminated"),
    # Not denied: reads, other commands of the same groups, and the words in
    # a quoted argument or a body file.
    ("allow", REPO, "gh -R marc272/parametric-insurance-design pr list"),
    ("allow", REPO, "gh release view v1.0.0 --repo marc272/crc-sdk --json createdAt"),
    ("allow", REPO, "gh workflow view release.yaml --repo marc272/crc-sdk --yaml"),
    ("allow", REPO, "gh repo view marc272/crc-sdk --json name"),
    (
        "allow",
        REPO,
        "gh pr merge 196 --squash --repo marc272/parametric-insurance-design",
    ),
    ("allow", REPO, 'git commit -m "MAR-263: deny gh -R x release create forms"'),
    ("allow", REPO, 'grep -rn "gh release create" docs/'),
    (
        "allow",
        REPO,
        "gh pr view 3 --repo marc272/crc-sdk --json body -q .body"
        " | grep -c RiskThinking",
    ),
    (
        "allow",
        AGENT_WT,
        'gh pr create --draft --title "[MAR-263] x" --body-file results/pr-body.md',
    ),
    ("allow", REPO, "gh --version && gh workflow list 'unterminated"),
    # MAR-282 item 2: gh repo archive, unarchive and rename, denied everywhere.
    ("deny", SDK, "gh repo archive"),
    ("deny", REPO, "gh repo archive marc272/crc-docs --yes"),
    ("deny", REPO, "gh repo unarchive marc272/crc-sdk -y"),
    ("deny", REPO, "gh repo rename crc-sdk-old -R marc272/crc-sdk --yes"),
    ("deny", DOCS, "gh repo rename crc-docs-old --yes"),
    ("deny", REPO, "bash -c 'gh repo archive marc272/crc-sdk -y'"),
    # MAR-282 item 3: commands with their own -R that take the clone's
    # repository without it, and gh repo view without a repository argument.
    # MAR-289: gh agent-task create, autolink create and deploy-key add are
    # denied everywhere now (refused in fork paths until then).
    ("deny", SDK, 'gh agent-task create "make the tests pass"'),
    ("deny", WT, "gh agent-task create -F task.md --base parametric"),
    ("deny", SDK, "gh agents create x"),
    ("refuse", DOCS, "gh agent-task view 3"),
    ("refuse", SDK, "gh repo autolink list"),
    ("deny", SDK, "gh repo autolink create JIRA- https://example.com/<num>"),
    ("deny", DOCS, "gh repo deploy-key add key.pub --allow-write"),
    ("refuse", SDK, "gh repo deploy-key list"),
    ("refuse", SDK, "gh repo read-file README.md"),
    ("refuse", SDK, "gh repo read-dir src --ref parametric"),
    ("refuse", SDK, "gh project link 3 --owner marc272"),
    ("refuse", SDK, "gh project unlink 3 --owner marc272"),
    ("refuse", SDK, "gh repo view"),
    ("refuse", DOCS, "gh repo view --web"),
    ("refuse", SDK, "gh repo view --json name -q .name"),
    ("refuse", SDK, "gh repo view --branch parametric"),
    ("refuse", SDK, "gh repo view crc-sdk"),
    ("refuse", REPO, f"cd {SDK} && gh repo view"),
    ("refuse", SDK, "gh rs list"),
    ("refuse", SDK, "gh repo autolink list 'unterminated"),
    ("deny", SDK, 'gh agent-task create "x" -R marc272/crc-sdk'),  # MAR-289
    ("allow", SDK, "gh agent-task list"),
    ("allow", SDK, "gh repo autolink list -R marc272/crc-sdk"),
    ("allow", SDK, "gh repo autolink -R marc272/crc-sdk list"),
    ("allow", DOCS, "gh repo deploy-key list --repo marc272/crc-docs"),
    ("allow", SDK, "gh repo read-file README.md -R marc272/crc-sdk --ref parametric"),
    ("allow", SDK, "gh project link 3 --owner marc272 -R marc272/crc-sdk"),
    ("allow", SDK, "gh repo view marc272/crc-sdk --json name"),
    ("allow", DOCS, "gh repo view https://github.com/marc272/crc-docs"),
    ("allow", SDK, "gh repo view -b parametric marc272/crc-sdk"),
    ("allow", SDK, "gh rs list -R marc272/crc-sdk"),
    ("allow", REPO, "gh repo view && gh repo autolink list && gh project link 3"),
    # MAR-282 item 4: a rerun of a fork's run, denied wherever it runs.
    ("deny", REPO, "gh run rerun 123 --repo marc272/crc-sdk"),
    ("deny", REPO, "gh run rerun 123 -R marc272/crc-docs --failed"),
    ("deny", REPO, "gh -R marc272/crc-sdk run rerun 123"),
    ("deny", REPO, "gh run -R marc272/crc-sdk rerun 123 --job 456"),
    ("deny", REPO, 'gh run rerun 123 --repo "$FORK"'),
    ("deny", SDK, "gh run rerun 123"),
    ("deny", DOCS, "gh run rerun 123 --failed"),
    ("deny", REPO, "gh api -X POST repos/marc272/crc-sdk/actions/runs/123/rerun"),
    (
        "deny",
        REPO,
        "gh api --method POST repos/marc272/crc-docs/actions/runs/1/rerun-failed-jobs",
    ),
    ("deny", REPO, "gh api -X POST repos/marc272/crc-sdk/actions/jobs/9/rerun"),
    ("deny", SDK, "gh api -X POST repos/:owner/:repo/actions/jobs/9/rerun"),
    ("deny", REPO, 'gh api -X POST "repos/marc272/$R/actions/runs/1/rerun"'),
    ("deny", REPO, "gh run rerun 3 -R marc272/crc-sdk 'unterminated"),
    ("allow", REPO, "gh run rerun 42122091157 --failed"),
    ("allow", SDK, "gh run rerun 1 --repo marc272/parametric-insurance-design"),
    ("allow", REPO, "gh run view 123 --repo marc272/crc-sdk --log-failed"),
    ("allow", REPO, "gh run cancel 123 --repo marc272/crc-sdk"),
    ("allow", REPO, "gh api repos/marc272/crc-sdk/actions/runs/123 --jq .rerun_url"),
    (
        "allow",
        REPO,
        'gh api -X POST "repos/marc272/parametric-insurance-design/actions/runs/$ID'
        '/rerun"',
    ),
    ("allow", REPO, "gh api -X POST repos/{owner}/{repo}/actions/runs/1/rerun"),
    # MAR-282 item 7: new gh commands, third-party code and other agents.
    ("deny", REPO, "gh alias set rc 'release create'"),
    ("deny", REPO, "gh alias set --shell x 'echo hi'"),
    ("deny", REPO, "gh alias import aliases.yml --clobber"),
    ("deny", REPO, "gh extension install someone/gh-thing"),
    ("deny", REPO, "gh ext install someone/gh-thing"),
    ("deny", REPO, "gh extensions install ."),
    ("deny", REPO, "gh skill install someone/skills pdf"),
    ("deny", REPO, "gh skills add someone/skills"),
    ("deny", REPO, "gh skill update --all"),
    ("deny", DOCS, "gh skill publish --tag v1.0.0"),
    ("deny", REPO, "gh skill publish --dry-run"),
    ("deny", REPO, 'gh copilot -p "fix the tests"'),
    ("deny", REPO, "gh copilot --remove"),
    ("allow", REPO, "gh alias list"),
    ("allow", REPO, "gh extension list && gh ext list"),
    ("allow", REPO, "gh skill list && gh skill search pdf"),
    ("allow", REPO, "gh skill preview someone/skills pdf"),
    # MAR-282 item 8: a subcommand, or a denied group's command, from an
    # expansion; a PR number, run ID or tag from one still passes.
    ("deny", REPO, "gh $c create v1"),
    ("deny", REPO, 'gh "$sub" create v1'),
    ("deny", REPO, "gh ${GH_GROUP} create v1"),
    ("deny", REPO, "gh $(echo release) create v1"),
    ("deny", REPO, "gh `echo release` create v1"),
    ("deny", REPO, "gh release $c v1"),
    ("deny", REPO, 'gh release "$(echo create)" v1'),
    ("deny", REPO, "gh release cre{ate,} v1"),
    ("deny", REPO, "gh workflow r?n release.yaml"),
    ("deny", REPO, "gh pr $m 3 --admin"),
    ("deny", REPO, "gh repo $c marc272/crc-docs --yes"),
    ("deny", REPO, "gh run $r 1 --repo marc272/crc-sdk"),
    ("deny", REPO, "gh -R marc272/crc-sdk $c create v1"),
    ("deny", REPO, 'for c in "release create"; do gh $c --help; done'),
    ("deny", REPO, "sh -c 'gh $0 create v1' release"),
    ("deny", REPO, "gh $c 'unterminated"),
    ("deny", REPO, 'grep -c gh "$f"'),
    ("allow", REPO, 'gh pr checks "$PR" --watch'),
    ("allow", SDK, 'gh pr view "$N" --repo marc272/crc-sdk --json title'),
    ("allow", REPO, 'gh run view "$RUN" --log-failed'),
    ("allow", REPO, 'gh release view "$TAG" --repo marc272/crc-sdk'),
    ("allow", REPO, "gh pr merge $N --squash"),
    (
        "allow",
        REPO,
        'gh api "repos/marc272/parametric-insurance-design/check-runs/$ID/annotations"',
    ),
    ("allow", REPO, "gh browse $N -n"),
    ("allow", REPO, "gh api graphql -f query='{viewer{login}}'"),
    # MAR-289 item 1: the issue's four forms of a tag reaching crc-sdk.
    ("deny", SDK, "git update-ref refs/tags/v1.0.0 HEAD"),
    ("deny", REPO, "git push origin 'v1.0.0'"),
    ("deny", REPO, "git push https://github.com/marc272/crc-sdk.git v1.0.0"),
    ("deny", SDK, "git push --mirror origin"),
    # The same, through -C, -c, a path, quotes, sh -c and the like.
    ("deny", REPO, f"git -C {SDK} update-ref refs/tags/v1.0.0 HEAD"),
    ("deny", REPO, f'git -C {SDK} push origin "v1.0.0"'),
    ("deny", REPO, f"git -C {WT} push git@github.com:marc272/crc-sdk.git v1.0.0"),
    ("deny", REPO, f"git -C {SDK} push origin --mirror"),
    ("deny", REPO, "/usr/bin/git push origin v1.0.0"),
    ("deny", REPO, '"git" push origin v1.0.0'),
    ("deny", REPO, "g\\it push origin v1.0.0"),
    ("deny", REPO, "git -c http.proxy=x push origin v1.0.0"),
    ("deny", REPO, "git --no-pager push origin v1.0.0"),
    ("deny", REPO, "bash -c 'git push origin v1.0.0'"),
    ("deny", REPO, "timeout 60 git push origin v1.0.0"),
    ("deny", REPO, 'echo "$(git push origin v1.0.0)"'),
    # git tag and update-ref in every spelling; --stdin can hold any ref.
    ("deny", REPO, "git tag v1.0.0"),
    ("deny", SDK, "git tag -a v1.0.0 -m release"),
    ("deny", REPO, "git -c user.name=x tag v1.0.0"),
    ("deny", REPO, "git update-ref -d refs/tags/v1.0.0"),
    ("deny", REPO, "git update-ref refs/TAGS/v1.0.0 HEAD"),
    ("deny", REPO, "git update-ref --stdin < refs.txt"),
    ("deny", REPO, 'git update-ref "$REF" HEAD'),
    # Flags that send tags or everything, abbreviated as git accepts them.
    ("deny", REPO, "git push --tags"),
    ("deny", REPO, "git push origin --tag"),
    ("deny", REPO, "git push --follow-tags origin marcprinzing/x"),
    ("deny", REPO, "git push --fol origin marcprinzing/x"),
    ("deny", REPO, "git push --mirr origin"),
    ("deny", REPO, "git push --m origin"),
    # Refspecs that name a tag, however they are written.
    ("deny", REPO, "git push origin refs/tags/v1.0.0"),
    ("deny", REPO, "git push origin HEAD:refs/tags/v1.0.0"),
    ("deny", REPO, "git push origin tags/v1.0.0"),
    ("deny", REPO, "git push origin tag v1.0.0"),
    ("deny", REPO, "git push origin tag some-name"),
    ("deny", REPO, "git push origin +v1.0.0"),
    ("deny", REPO, "git push origin HEAD:v1.0.0"),
    ("deny", REPO, "git push origin my-tag:v1.0.0"),
    ("deny", REPO, "git push origin :v1.0.0"),
    ("deny", REPO, "git push -u origin -- v1.0.0"),
    ("deny", REPO, "git push origin 'refs/*:refs/*'"),
    # Expansions: the hook can't tell what they would push.
    ("deny", REPO, 'git push origin "$TAG"'),
    ("deny", REPO, "git push origin $(git describe --tags)"),
    ("deny", REPO, "git push $ARGS"),
    ("deny", REPO, "git $c origin v1.0.0"),
    ("deny", REPO, 'git -c "$K=true" push origin marcprinzing/x'),
    # Configuration that makes a plain push carry tags, or adds a command.
    ("deny", REPO, "git -c push.followTags=true push origin marcprinzing/x"),
    ("deny", REPO, "git -c remote.origin.push=refs/tags/* push origin"),
    ("deny", REPO, "git -c remote.origin.mirror=true push origin"),
    ("deny", REPO, "git -c alias.p='push origin v1.0.0' p"),
    ("deny", REPO, "git --config-env=push.followTags=X push origin marcprinzing/x"),
    ("deny", REPO, "git config push.followTags true"),
    ("deny", REPO, "git config --global push.followtags true"),
    ("deny", REPO, "git config set alias.p push"),
    ("deny", REPO, "git config --add remote.origin.push 'refs/tags/*'"),
    ("deny", REPO, "git config alias.get get"),
    ("deny", REPO, "git remote add --mirror=push x https://github.com/marc272/crc-sdk"),
    # The plumbing under push.
    ("deny", REPO, "git send-pack --mirror https://github.com/marc272/crc-sdk.git"),
    ("deny", REPO, "git http-push https://github.com/marc272/crc-sdk.git v1.0.0"),
    # Operands the hook can't see, and what xargs may still run.
    ("deny", REPO, "echo v1.0.0 | xargs git push origin"),
    ("deny", REPO, "xargs git update-ref < refs.txt"),
    ("allow", REPO, "git ls-files -z '*.md' | xargs -0 git add"),
    # Commands the hook can't parse.
    ("deny", REPO, "git push origin v1.0.0 'unterminated"),
    ("deny", REPO, "git update-ref refs/tags/v1 HEAD 'unterminated"),
    ("deny", REPO, "git tag v1 'unterminated"),
    ("deny", REPO, f"git -C {SDK} push --mirror origin 'unterminated"),
    ("allow", REPO, "git push -u origin marcprinzing/x 'unterminated"),
    ("allow", REPO, "git commit -m 'unterminated tag v1"),
    # The prescribed pushes, and everything else git does with tags, pass.
    ("allow", WT, "git push -u origin marcprinzing/mar-260-step-payout"),
    ("allow", REPO, f"git -C {WT} push -u origin marcprinzing/mar-260-step-payout"),
    ("allow", REPO, f"git -C {WT} push -u origin sync/upstream-main-2026-11-05"),
    ("allow", REPO, 'git -C "$WT" push -u origin marcprinzing/mar-260-step-payout'),
    ("allow", AGENT_WT, "git push -u origin HEAD"),
    ("allow", AGENT_WT, "git push"),
    ("allow", REPO, "git push origin"),
    ("allow", REPO, "git push --dry-run -v origin HEAD"),
    ("allow", REPO, "git push origin HEAD:refs/heads/marcprinzing/mar-1-x"),
    ("allow", REPO, "git push origin HEAD:refs/heads/v1-branch"),
    ("allow", REPO, "git push origin --delete marcprinzing/mar-1-x"),
    ("allow", REPO, "git push -o ci.skip -u origin marcprinzing/mar-1-x"),
    ("allow", SDK, "git for-each-ref refs/tags && git ls-remote --tags origin"),
    ("allow", SDK, "git fetch upstream --tags"),
    ("allow", REPO, "git describe --tags --abbrev=0 && git log --tags -3"),
    ("allow", REPO, 'git commit -m "tag v1.0.0 with git push origin v1.0.0"'),
    ("allow", REPO, "git update-ref refs/heads/marcprinzing/x HEAD"),
    ("allow", REPO, 'git update-ref -m "$MSG" refs/heads/marcprinzing/x HEAD'),
    ("allow", REPO, "git config --get push.followTags && git config --list"),
    ("allow", REPO, "git config get alias.p"),
    ("allow", REPO, 'git config user.name "$NAME"'),
    ("allow", REPO, 'git -c user.name="$NAME" commit -m x'),
    ("allow", REPO, "git remote add mine https://github.com/marc272/crc-docs.git"),
    ("allow", REPO, "git help tag && git --version"),
    # MAR-289 item 5: deploy keys, autolinks and gists, denied everywhere.
    ("deny", REPO, "gh repo deploy-key add key.pub --allow-write -R marc272/crc-sdk"),
    ("deny", REPO, "gh repo deploy-key add key.pub -w"),
    ("deny", REPO, "gh repo deploy-key -R marc272/crc-sdk add key.pub"),
    ("deny", DOCS, "gh repo deploy-key delete 123"),
    ("deny", REPO, "gh repo deploy-key delete 123 --repo marc272/crc-docs --yes"),
    ("deny", REPO, "gh repo autolink create JIRA- https://example.com/x"),
    ("deny", REPO, "gh repo autolink new JIRA- https://example.com/x"),
    ("deny", REPO, "gh repo autolink -R marc272/crc-sdk delete 5 --yes"),
    ("deny", REPO, 'gh repo deploy-key "$a" key.pub'),
    ("deny", REPO, "gh repo autolink $c JIRA- x"),
    ("deny", REPO, "gh repo deploy-key add key.pub 'unterminated"),
    ("deny", REPO, "gh gist create notes.md --public"),
    ("deny", REPO, "gh gist new notes.md"),
    ("deny", REPO, "echo hi | gh gist create -"),
    ("deny", REPO, "gh gist $c notes.md"),
    ("deny", REPO, "gh gist create notes.md 'unterminated"),
    ("allow", REPO, "gh repo deploy-key list --repo marc272/crc-sdk"),
    ("allow", REPO, "gh repo autolink view 5 -R marc272/crc-sdk"),
    ("allow", REPO, "gh repo deploy-key list && gh repo autolink list"),
    ("allow", REPO, "gh gist list && gh gist view abc123"),
    # MAR-289 item 6: agent tasks, gh's program settings and the token.
    ("deny", REPO, "gh agent-task create x"),
    ("deny", REPO, "gh agents create x"),
    ("deny", REPO, "gh agent create x"),
    ("deny", REPO, "gh agent-tasks create -F task.md"),
    ("deny", REPO, "gh agent-task create x 'unterminated"),
    ("deny", REPO, "gh config set editor vim"),
    ("deny", REPO, "gh config set pager 'less -R'"),
    ("deny", REPO, "gh config set browser x --host github.com"),
    ("deny", REPO, "gh config set -h github.com editor vim"),
    ("deny", REPO, "gh config set --host github.com pager cat"),
    ("deny", REPO, 'gh config set "$k" vim'),
    ("deny", REPO, "gh config $c editor vim"),
    ("deny", REPO, "gh config set editor 'unterminated"),
    ("deny", REPO, "gh auth token"),
    ("deny", REPO, "gh auth token --hostname github.com"),
    ("deny", REPO, "gh auth status --show-token"),
    ("deny", REPO, "gh auth status -t"),
    ("deny", REPO, "gh auth status -at"),
    ("deny", REPO, "gh auth token 'unterminated"),
    ("deny", REPO, "gh auth status --show-token 'unterminated"),
    ("allow", REPO, "gh agent-task list"),
    ("allow", REPO, "gh config get editor && gh config list"),
    ("allow", REPO, "gh config set prompt disabled"),
    ("allow", REPO, "gh config set git_protocol https --host github.com"),
    ("allow", REPO, "gh auth status"),
    ("allow", REPO, "gh auth status --active -h github.com"),
    ("allow", REPO, "gh auth status --json hosts"),
    # MAR-289 item 6: gh and git from a variable, flags from a variable.
    ("deny", REPO, "$GH release create v1"),
    ("deny", REPO, '"$GH" -R marc272/crc-sdk workflow run release.yaml'),
    ("deny", REPO, "${GH} pr merge 3 --admin"),
    ("deny", REPO, "$(which gh) release create v1"),
    ("deny", REPO, "`which gh` repo delete marc272/crc-docs --yes"),
    ("deny", REPO, "timeout 60 $GH workflow run release.yaml"),
    ("deny", REPO, "$GH gist create notes.md"),
    ("deny", REPO, "$GH -R RiskThinking/crc-sdk pr list"),
    ("deny", REPO, "$GIT push origin v1.0.0"),
    ("deny", SDK, '"$GIT" tag v1.0.0'),
    ("deny", REPO, "gh pr merge 3 $X"),
    ("deny", REPO, 'gh pr merge 3 --squash "$X"'),
    ("deny", REPO, 'gh pr merge "$N" --squash "$@"'),
    ("deny", REPO, "gh pr merge 3 --$X"),
    ("deny", REPO, "gh -R marc272/crc-sdk pr merge 3 $X"),
    (
        "allow",
        REPO,
        'gh pr merge "$N" --repo marc272/crc-sdk --squash --subject "$S" --body "$B"',
    ),
    ("allow", REPO, 'gh pr merge 3 --squash --subject="$S" -b "$B"'),
    ("allow", REPO, 'gh pr merge 3 --squash -t"$S" -F "$BODY_FILE"'),
    ("allow", REPO, 'gh pr merge -- "$N" "$X"'),
    ("allow", REPO, "$PY -m pytest -q"),
    ("allow", WT, "$UV run pytest -q"),
    ("allow", REPO, '"$EDITOR" notes.md'),
    ("allow", REPO, "$X $Y"),
    ("allow", REPO, "$PY tools/x.py RiskThinking/crc-sdk"),
    ("allow", REPO, '$DOCKER push "$IMAGE"'),
    # MAR-306: Actions stay off on crc-docs; reading the setting passes.
    (
        "deny",
        REPO,
        "gh api -X PUT repos/marc272/crc-docs/actions/permissions -F enabled=true",
    ),
    (
        "deny",
        REPO,
        "gh api --method PUT repos/marc272/crc-docs/actions/permissions"
        " -F enabled=true -f allowed_actions=all",
    ),
    (
        "deny",
        REPO,
        "gh api --method=PUT repos/marc272/crc-docs/actions/permissions/workflow"
        " -f default_workflow_permissions=read",
    ),
    (
        "deny",
        REPO,
        "gh api -XPUT repos/marc272/crc-docs/actions/permissions -F enabled=true",
    ),
    ("deny", REPO, "gh api repos/marc272/crc-docs/actions/permissions -F enabled=true"),
    (
        "deny",
        REPO,
        "gh api repos/marc272/crc-docs/actions/permissions --input body.json",
    ),
    ("deny", REPO, 'gh api -X "$M" repos/marc272/crc-docs/actions/permissions'),
    (
        "deny",
        REPO,
        'gh api -X PUT "repos/marc272/$R/actions/permissions" -F enabled=true',
    ),
    (
        "deny",
        DOCS,
        "gh api -X PUT repos/{owner}/{repo}/actions/permissions -F enabled=true",
    ),
    ("allow", REPO, "gh api repos/marc272/crc-docs/actions/permissions --jq .enabled"),
    ("allow", REPO, "gh api -X GET repos/marc272/crc-docs/actions/permissions"),
    ("allow", REPO, "gh api repos/marc272/crc-sdk/actions/permissions --jq .enabled"),
    # MAR-306: the form the runbook prescribes for a sync PR on a MAR branch.
    (
        "allow",
        REPO,
        "gh pr merge 2 --repo marc272/crc-docs --merge"
        ' --subject "chore: merge upstream main into parametric (#2)"'
        ' --body "Refs: MAR-300"',
    ),
]

# --- The deny rules (MAR-263) ----------------------------------------------
#
# Claude Code loads .claude/settings.json at session start, so a new rule
# can't be tried live in the session that writes it. ``denied_by`` models how
# the permissions page (code.claude.com/docs/en/permissions, read 2026-11-06)
# says a Bash deny rule matches, and ``DOC_RULE_EXAMPLES`` checks the model
# against the page's own examples:
#
# - "Wildcard patterns": ``*`` stands for any text, spaces included, and the
#   rest of the pattern is matched as written against the whole command. A
#   trailing `` *`` that is the rule's only wildcard also matches the bare
#   command, and a trailing ``:*`` is the same as `` *``.
# - "Compound commands": a deny rule applies when any subcommand matches. The
#   command is split at &&, ||, ;, |, |&, & and newlines, and commands in
#   subshells and command substitutions count too.
# - "Wrappers": timeout, time, nice, nohup, stdbuf, command, builtin, noglob
#   and xargs without flags are stripped, and so is any leading assignment.
# - "What a Bash rule doesn't match": quotes and paths count as written, so
#   ``git 'push'`` and ``/usr/bin/curl`` match neither ``git push *`` nor
#   ``curl *``.
#
# What the page doesn't say isn't modelled (whether runs of spaces are
# collapsed, how here-documents split), and the cases avoid those forms.
_RULE_SEPARATORS = ("&&", "||", "|&", ";", "|", "&", "\n")
_RULE_ASSIGNMENT = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*=(?:'[^']*'|\"[^\"]*\"|[^\s'\"])*\s+"
)
_PLAIN_WRAPPERS = frozenset({"time", "nohup", "noglob", "builtin", "command"})


def rule_matches(pattern: str, command: str) -> bool:
    """Whether the pattern of a ``Bash(<pattern>)`` rule matches a command.

    Parameters
    ----------
    pattern
        The text between ``Bash(`` and ``)``.
    command
        One simple command, as written.

    Returns
    -------
    bool
        Whether the rule matches, as "Wildcard patterns" describes.
    """
    if pattern.endswith(":*"):
        pattern = pattern[:-2] + " *"
    regex = ".*".join(re.escape(part) for part in pattern.split("*"))
    if pattern.endswith(" *") and pattern.count("*") == 1:
        regex = re.escape(pattern[:-2]) + "(?: .*)?"
    return re.fullmatch(regex, command, re.DOTALL) is not None


def _closing(text: str, i: int) -> tuple[int, list[str]]:
    """Return the end of the quote or substitution at ``i``, and its scripts.

    ``i`` is at a double quote, a ``$(`` or a backtick. The scripts are the
    contents of the command substitutions in it.
    """
    n = len(text)
    if text[i] == "`":
        j = i + 1
        while j < n and text[j] != "`":
            j += 2 if text[j] == "\\" else 1
        return min(j + 1, n), [text[i + 1 : j]]
    if text[i] == '"':
        scripts: list[str] = []
        j = i + 1
        while j < n and text[j] != '"':
            if text[j] == "\\":
                j += 2
            elif text.startswith("$(", j) or text[j] == "`":
                j, inner = _closing(text, j)
                scripts += inner
            else:
                j += 1
        return min(j + 1, n), scripts
    depth, j = 1, i + 2  # $(
    while j < n:
        if text[j] == "\\":
            j += 2
            continue
        if text[j] == "'":
            end = text.find("'", j + 1)
            j = n if end < 0 else end + 1
            continue
        if text[j] == '"':
            j, _ = _closing(text, j)
            continue
        depth += {"(": 1, ")": -1}.get(text[j], 0)
        if depth == 0:
            return j + 1, [text[i + 2 : j]]
        j += 1
    return n, [text[i + 2 :]]


def subcommands(command: str) -> list[str]:
    """Return the simple commands of shell text, as written, nested ones too.

    Parameters
    ----------
    command
        Shell command text.

    Returns
    -------
    list of str
        Each simple command, stripped of surrounding space: the top-level
        ones, then those in subshells and command substitutions.
    """
    found: list[str] = []
    nested: list[str] = []
    current: list[str] = []

    def flush() -> None:
        text = "".join(current).strip()
        current.clear()
        if text:
            found.append(text)

    i, n = 0, len(command)
    while i < n:
        c = command[i]
        if c == "\\":
            current.append(command[i : i + 2])
            i += 2
        elif c == "'":
            end = command.find("'", i + 1)
            end = n if end < 0 else end + 1
            current.append(command[i:end])
            i = end
        elif c in '"`' or command.startswith("$(", i):
            end, scripts = _closing(command, i)
            for script in scripts:
                nested += subcommands(script)
            current.append(command[i:end])
            i = end
        elif c in "()":
            flush()
            i += 1
        else:
            sep = next((s for s in _RULE_SEPARATORS if command.startswith(s, i)), "")
            if sep:
                flush()
                i += len(sep)
            else:
                current.append(c)
                i += 1
    flush()
    return found + nested


def strip_wrappers(command: str) -> str:
    """Return a simple command without its leading assignments and wrappers.

    Parameters
    ----------
    command
        One simple command, as written.

    Returns
    -------
    str
        The command after the wrappers that "Wrappers" lists.
    """
    while True:
        assignment = _RULE_ASSIGNMENT.match(command)
        if assignment:
            command = command[assignment.end() :]
            continue
        words = command.split()
        first = words[0] if words else ""
        skip = 0
        if first in _PLAIN_WRAPPERS and words[1:2] != ["-v"]:
            skip = 1
        elif first == "timeout":
            skip = 1
            while skip < len(words) and words[skip].startswith("-"):
                skip += 2 if words[skip] in ("-s", "-k") else 1
            skip += 1  # the duration
        elif first == "nice":
            skip = 3 if words[1:2] == ["-n"] else 1
        elif first == "stdbuf":
            skip = 1
            while skip < len(words) and words[skip].startswith("-"):
                skip += 1
        elif first == "xargs" and words[1:2] and not words[1].startswith("-"):
            skip = 1
        if not skip or skip >= len(words):
            return command
        command = command.split(None, skip)[skip]


def bash_deny_patterns(settings: dict[str, object]) -> list[str]:
    """Return the patterns of the ``Bash(...)`` deny rules of a settings object.

    Parameters
    ----------
    settings
        A parsed settings file.

    Returns
    -------
    list of str
        The text between ``Bash(`` and ``)`` of each Bash deny rule.
    """
    permissions = settings.get("permissions")
    deny = permissions.get("deny", []) if isinstance(permissions, dict) else []
    return [
        rule[len("Bash(") : -1]
        for rule in deny
        if isinstance(rule, str) and rule.startswith("Bash(") and rule.endswith(")")
    ]


def denied_by(command: str, patterns: list[str]) -> str | None:
    """Return the first deny rule that refuses ``command``, or ``None``.

    Parameters
    ----------
    command
        Shell command text, as the Bash tool receives it.
    patterns
        Bash deny patterns (``bash_deny_patterns``).

    Returns
    -------
    str or None
        The rule, as ``Bash(<pattern>)``, or ``None`` if none matches.
    """
    for sub in subcommands(command):
        for form in dict.fromkeys((sub, strip_wrappers(sub))):
            for pattern in patterns:
                if rule_matches(pattern, form):
                    return f"Bash({pattern})"
    return None


# (pattern, command, matches) from the permissions page: the "Wildcard
# patterns" table, and the examples under "Compound commands", "Wrappers" and
# "What a Bash rule doesn't match".
DOC_RULE_EXAMPLES: list[tuple[str, str, bool]] = [
    ("npm run build", "npm run build", True),
    ("npm run build", "npm run build --watch", False),
    ("npm run *", "npm run build", True),
    ("npm run *", "npm run test --watch", True),
    ("npm run *", "npm run", True),
    ("npm run *", "npm install", False),
    ("git log * main", "git log --oneline main", True),
    ("git log * main", "git log --output=<file> main", True),
    ("git log * main", "git log main", False),
    ("git log * main", "git push origin main", False),
    ("git * main", "git merge main", True),
    ("git * main", "git push origin main", True),
    ("git * main", "git -c core.fsmonitor=<script> diff main", True),
    ("git * main", "git log", False),
    ("* --version", "node --version", True),
    ("* --version", "bash -c 'echo hi' --version", True),
    ("* --version", "node -v", False),
    ("ls *", "ls -la", True),
    ("ls *", "ls", True),
    ("ls *", "lsof", False),
    ("ls*", "ls -la", True),
    ("ls*", "lsof", True),
    ("* --help *", "npm --help x", True),
    ("* --help *", "npm --help", False),
    ("ls:*", "ls -la", True),
    ("git clean *", "cd /tmp && git clean -f", True),
    ("git clean *", 'echo "$(git clean -f)"', True),
    ("npm test *", "timeout 30 npm test", True),
    ("rm *", "FOO=bar rm -rf tmp/", True),
    ("grep *", "xargs grep pattern", True),
    ("grep *", "xargs -n1 grep pattern", False),
    ("curl *", "curl https://example.com", True),
    ("curl *", "/usr/bin/curl https://example.com", False),
    ("curl *", "sh -c 'curl https://example.com'", False),
    ("rm *", "bash -c 'rm -rf build/'", False),
    ("git push *", "git push origin main", True),
    ("git push *", "git -C . push origin main", False),
    ("git push *", "git -c push.default=current push origin main", False),
    ("git push *", "git 'push' origin main", False),
]

# (deny rules, hook, command): what the deny rules of .claude/settings.json
# do with a command ("deny" or "pass", by denied_by), and what the hook does
# with it from this repository's main checkout. Commands are written as an
# agent would write them.
RULE_CASES: list[tuple[str, str, str]] = [
    # The issue's three gh -R forms (MAR-263), and the other spellings and
    # positions of the repo flag.
    ("deny", "deny", "gh -R marc272/crc-sdk workflow run release.yaml"),
    ("deny", "deny", "gh -R marc272/crc-sdk release create v1"),
    ("deny", "deny", "gh -R marc272/crc-sdk pr merge 3 --admin"),
    ("deny", "deny", "gh --repo marc272/crc-sdk release upload v1 dist/a.whl"),
    ("deny", "deny", "gh --repo=marc272/crc-sdk workflow enable release.yaml"),
    ("deny", "deny", "gh -Rmarc272/crc-sdk release delete v1 --yes"),
    ("deny", "deny", "gh -R=marc272/crc-sdk workflow disable ci.yml"),
    ("deny", "deny", "gh -R marc272/crc-sdk release edit v1 --draft=false"),
    ("deny", "deny", "gh -R marc272/crc-sdk release delete-asset v1 a.whl"),
    ("deny", "deny", "gh release -R marc272/crc-sdk create v1"),
    ("deny", "deny", "gh release --repo marc272/crc-sdk upload v1 a.whl"),
    ("deny", "deny", "gh workflow --repo marc272/crc-sdk run release.yaml"),
    ("deny", "deny", "gh workflow -R marc272/crc-sdk enable release.yaml"),
    ("deny", "deny", "gh pr -R marc272/crc-sdk merge 3 --squash --admin"),
    # The aliases gh release new and gh repo new, and --admin=<value>.
    ("deny", "deny", "gh release new v1.2.3"),
    ("deny", "deny", "gh -R marc272/crc-sdk release new v1.2.3"),
    ("deny", "deny", "gh release -R marc272/crc-sdk new v1.2.3"),
    ("deny", "deny", "gh repo new crc-scratch --public"),
    ("deny", "deny", "gh pr merge 3 --admin=true"),
    ("deny", "deny", "gh pr merge --admin 3"),
    (
        "deny",
        "deny",
        "gh --repo marc272/parametric-insurance-design pr merge 196 --squash --admin",
    ),
    # A RiskThinking repository, in any position and quoting.
    ("deny", "deny", "gh -R RiskThinking/crc-sdk pr create --title t --body b"),
    ("deny", "deny", "gh --repo RiskThinking/crc-sdk issue create --title t"),
    ("deny", "deny", "gh --repo=riskthinking/crc-docs pr list"),
    ("deny", "deny", "gh pr create -RRiskThinking/crc-sdk --title t"),
    ("deny", "deny", "gh pr create -R=RiskThinking/crc-sdk --title t"),
    ("deny", "deny", 'gh pr create --repo "RiskThinking/crc-sdk" --title t'),
    ("deny", "deny", "gh repo view RiskThinking/crc-sdk"),
    ("deny", "deny", "gh repo clone RiskThinking/crc-docs"),
    (
        "deny",
        "deny",
        "gh pr comment 3 --repo marc272/crc-sdk"
        ' --body "port of RiskThinking/crc-sdk#12"',
    ),
    # The forms the rules denied before, still denied.
    ("deny", "deny", "gh release create v1"),
    ("deny", "deny", "gh workflow run release.yaml"),
    ("deny", "deny", "gh pr merge 3 --squash --admin"),
    ("deny", "deny", "gh pr create --repo RiskThinking/crc-sdk --title t"),
    ("deny", "deny", "gh api repos/RiskThinking/crc-sdk/pulls"),
    ("deny", "deny", "gh repo delete marc272/crc-docs --yes"),
    ("deny", "refuse", "GH_REPO=RiskThinking/crc-sdk gh pr list"),
    ("deny", "allow", "gh api -X DELETE repos/marc272/crc-sdk/actions/caches/1"),
    ("deny", "deny", "git tag v1.0.0"),  # MAR-289: the hook too
    ("deny", "deny", "git push origin v1.0.0"),  # MAR-289: the hook too
    ("deny", "allow", f"git -C {WT} push --force origin x"),
    # Through wrappers, assignments, compound commands and substitutions.
    ("deny", "deny", f"cd {SDK} && gh -R marc272/crc-sdk release create v1"),
    ("deny", "deny", "timeout 60 gh -R marc272/crc-sdk workflow run release.yaml"),
    ("deny", "deny", "GH_DEBUG=1 gh -R marc272/crc-sdk release create v1"),
    ("deny", "deny", 'echo "$(gh -R marc272/crc-sdk release create v1)"'),
    # Spellings the text rules miss, as the permissions page says they do;
    # the hook refuses them.
    ("pass", "deny", "/opt/homebrew/bin/gh -R marc272/crc-sdk release create v1"),
    ("pass", "deny", "bash -c 'gh release create v1'"),
    ("pass", "deny", '"gh" -R marc272/crc-sdk workflow run release.yaml'),
    ("pass", "deny", "echo v1 | xargs -n1 gh release create"),
    ("pass", "deny", "gh -R marc272/crc-sdk release -R marc272/crc-sdk create v1"),
    ("pass", "deny", "gh pr list -R RISKTHINKING/crc-sdk"),
    # The rules' known false positives: a body that says "workflow run" after
    # a leading -R, and a release read that asks for createdAt with -R after
    # the group. Pass the body with --body-file, or the flag after the command.
    (
        "deny",
        "allow",
        'gh -R marc272/parametric-insurance-design pr comment 196 --body "the'
        ' workflow run failed"',
    ),
    ("deny", "allow", "gh release -R marc272/crc-sdk view v1 --json createdAt"),
    # The runbook's prescribed commands, and reads of the same groups: none is
    # denied.
    ("pass", "allow", "gh -R marc272/parametric-insurance-design pr list"),
    (
        "pass",
        "allow",
        "gh pr merge 196 --repo marc272/parametric-insurance-design --squash",
    ),
    (
        "pass",
        "allow",
        "gh pr merge 12 --repo marc272/crc-sdk --squash"
        ' --subject "feat(parametric): add the step payout (#12)"'
        ' --body "Refs: MAR-260"',
    ),
    ("pass", "allow", "gh pr merge 13 --repo marc272/crc-sdk --merge"),
    (
        "pass",
        "allow",
        "gh pr create --repo marc272/crc-sdk --base parametric"
        " --head marcprinzing/mar-260-step-payout --draft"
        ' --title "[MAR-260] feat(parametric): add the step payout"'
        f" --body-file {WT}-notes/pr-body.md",
    ),
    (
        "pass",
        "allow",
        "gh pr create --repo marc272/crc-sdk --base parametric"
        " --head sync/upstream-main-2026-11-05"
        ' --title "chore: merge upstream main into parametric"',
    ),
    ("pass", "allow", "gh pr checks 12 --repo marc272/crc-sdk --watch"),
    ("pass", "allow", "gh pr ready 12 --repo marc272/crc-sdk"),
    (
        "pass",
        "allow",
        "gh pr list --repo marc272/crc-docs --state open"
        " --json number,title,headRefName,baseRefName,isDraft,statusCheckRollup",
    ),
    ("pass", "allow", "gh repo set-default --view"),
    (
        "pass",
        "allow",
        "gh api repos/marc272/parametric-insurance-design/check-runs/42122091157"
        "/annotations",
    ),
    (
        "pass",
        "allow",
        "gh release download v1.6.40 -R quarto-dev/quarto-cli"
        " -p 'quarto-1.6.40-macos.tar.gz' -p 'quarto-1.6.40-checksums.txt'",
    ),
    ("pass", "allow", "gh release view v1.0.0 --repo marc272/crc-sdk --json createdAt"),
    ("pass", "allow", "gh release list -R marc272/crc-sdk"),
    ("pass", "allow", "gh -R marc272/crc-sdk workflow view release.yaml"),
    ("pass", "allow", "gh run list --repo marc272/crc-sdk --workflow release.yaml"),
    ("pass", "allow", "gh run rerun 42122091157 --failed"),
    ("pass", "allow", f"git -C {SDK} remote get-url --push upstream"),
    ("pass", "allow", f"git -C {SDK} fetch upstream && git -C {SDK} fetch origin"),
    (
        "pass",
        "allow",
        f"git -C {SDK} worktree add --no-track -b marcprinzing/mar-260-step-payout"
        f" {WT} origin/parametric",
    ),
    ("pass", "allow", f"git -C {WT} push -u origin marcprinzing/mar-260-step-payout"),
    (
        "pass",
        "allow",
        f"git -C {SDK} merge-base --is-ancestor upstream/main origin/parametric",
    ),
    ("pass", "allow", f"git -C {WT} merge --no-edit upstream/main"),
    (
        "pass",
        "allow",
        f"git -C {WT} diff origin/parametric... | grep -nE 'MAR-[0-9]+|linear\\.app'",
    ),
    ("pass", "allow", "git for-each-ref refs/tags && git ls-remote --tags origin"),
    ("pass", "allow", 'git commit -m "MAR-263: deny gh -R x release create forms"'),
    (
        "pass",
        "allow",
        'gh pr create --draft --title "[MAR-263] x" --body-file results/pr-body.md',
    ),
    # MAR-282: gh repo archive, unarchive and rename (item 2).
    ("deny", "deny", "gh repo archive marc272/crc-docs --yes"),
    ("deny", "deny", "gh repo unarchive marc272/crc-sdk -y"),
    ("deny", "deny", "gh repo rename crc-sdk-old -R marc272/crc-sdk --yes"),
    # MAR-282: a rerun of a fork's run, every position of the repo flag, and
    # the REST endpoints (item 4).
    ("deny", "deny", "gh run rerun 123 --repo marc272/crc-sdk"),
    ("deny", "deny", "gh run rerun 123 -R marc272/crc-docs --failed"),
    ("deny", "deny", "gh -R marc272/crc-sdk run rerun 123"),
    ("deny", "deny", "gh --repo=marc272/crc-docs run rerun 123"),
    ("deny", "deny", "gh run -R marc272/crc-sdk rerun 123"),
    ("deny", "deny", "gh run --repo marc272/crc-docs rerun 123"),
    ("deny", "deny", "gh api -X POST repos/marc272/crc-sdk/actions/runs/123/rerun"),
    (
        "deny",
        "deny",
        "gh api --method POST repos/marc272/crc-docs/actions/runs/1/rerun-failed-jobs",
    ),
    ("deny", "deny", "gh api -X POST repos/marc272/crc-sdk/actions/jobs/9/rerun"),
    # MAR-282: new gh commands, third-party code and other agents (item 7).
    ("deny", "deny", "gh alias set rc 'release create'"),
    ("deny", "deny", "gh alias import aliases.yml"),
    ("deny", "deny", "gh extension install someone/gh-thing"),
    ("deny", "deny", "gh extensions install ."),
    ("deny", "deny", "gh ext install someone/gh-thing"),
    ("deny", "deny", "gh skill install someone/skills pdf"),
    ("deny", "deny", "gh skill add someone/skills"),
    ("deny", "deny", "gh skill update --all"),
    ("deny", "deny", "gh skill publish --tag v1.0.0"),
    ("deny", "deny", "gh skills install someone/skills"),
    ("deny", "deny", "gh skills add someone/skills"),
    ("deny", "deny", "gh skills update --all"),
    ("deny", "deny", "gh skills publish --dry-run"),
    ("deny", "deny", 'gh copilot -p "fix the tests"'),
    ("deny", "deny", "gh copilot"),
    # MAR-282: what only the hook catches (item 8, and quoting), and the new
    # rules' known false positive.
    ("pass", "deny", "gh $c create v1"),
    ("pass", "deny", "gh release cre{ate,} v1"),
    ("pass", "deny", 'gh run rerun 123 --repo "$FORK"'),
    ("pass", "deny", 'gh "repo" archive marc272/crc-docs --yes'),
    (
        "deny",
        "allow",
        'gh -R marc272/crc-sdk pr comment 3 --body "the run rerun failed"',
    ),
    # MAR-282: the reads and this repository's reruns still pass.
    ("pass", "allow", "gh run rerun 1 --repo marc272/parametric-insurance-design"),
    ("pass", "allow", "gh run view 123 --repo marc272/crc-sdk --log-failed"),
    ("pass", "allow", "gh api repos/marc272/crc-sdk/actions/runs/123 --jq .rerun_url"),
    ("pass", "allow", "gh repo view marc272/crc-sdk --json name"),
    ("pass", "allow", "gh repo list marc272"),
    ("pass", "allow", "gh alias list && gh extension list && gh skill list"),
    # MAR-289 item 1: the issue's four forms, which passed the rules until now.
    ("deny", "deny", "git update-ref refs/tags/v1.0.0 HEAD"),
    ("deny", "deny", "git push origin 'v1.0.0'"),
    ("deny", "deny", "git push https://github.com/marc272/crc-sdk.git v1.0.0"),
    ("deny", "deny", "git push --mirror origin"),
    # Their other usual forms, -C included.
    ("deny", "deny", f"git -C {SDK} update-ref refs/tags/v1.0.0 HEAD"),
    ("deny", "deny", "git update-ref --stdin < refs.txt"),
    ("deny", "deny", f"git -C {SDK} update-ref --stdin < refs.txt"),
    ("deny", "deny", 'git push origin "v1.0.0"'),
    ("deny", "deny", f"git -C {SDK} push origin 'v1.0.0'"),
    ("deny", "deny", f'git -C {SDK} push origin "v1.0.0"'),
    (
        "deny",
        "deny",
        f"git -C {SDK} push https://github.com/marc272/crc-sdk.git v1.0.0",
    ),
    ("deny", "deny", "git push -u origin v1.0.0"),
    ("deny", "deny", "git push origin HEAD:v1.0.0"),
    ("deny", "deny", f"git -C {SDK} push origin HEAD:v1.0.0"),
    ("deny", "deny", "git push origin --mirror"),
    ("deny", "deny", f"git -C {SDK} push --mirror origin"),
    ("deny", "deny", f"git -C {SDK} push origin --mirror"),
    ("deny", "deny", "git push origin refs/tags/v1.0.0"),
    # What only the hook sees: the rules match the text as written.
    ("pass", "deny", "/usr/bin/git push origin v1.0.0"),
    ("pass", "deny", "bash -c 'git push origin v1.0.0'"),
    ("pass", "deny", '"git" tag v1.0.0'),
    ("pass", "deny", "git -c user.name=x tag v1.0.0"),
    ("pass", "deny", "git -c push.followTags=true push origin marcprinzing/x"),
    ("pass", "deny", "git config alias.p 'push origin v1.0.0'"),
    ("pass", "deny", "git push --mirr origin"),
    ("pass", "deny", 'git push origin "$TAG"'),
    ("pass", "deny", "git send-pack --mirror https://github.com/marc272/crc-sdk.git"),
    # The prescribed pushes pass both layers.
    ("pass", "allow", f"git -C {WT} push -u origin sync/upstream-main-2026-11-05"),
    (
        "pass",
        "allow",
        "git push -u origin marcprinzing/mar-289-r-11i-guard-follow-ups-after-mar-282",
    ),
    ("pass", "allow", "git push -u origin HEAD"),
    ("pass", "allow", "git push --dry-run -v origin HEAD"),
    ("pass", "allow", "git push"),
    ("pass", "allow", "git update-ref refs/heads/marcprinzing/x HEAD"),
    # MAR-289 item 5: deploy keys, autolinks and gists.
    ("deny", "deny", "gh repo deploy-key add key.pub --allow-write"),
    ("deny", "deny", "gh repo deploy-key delete 123"),
    ("deny", "deny", "gh repo deploy-key -R marc272/crc-sdk add key.pub"),
    ("deny", "deny", "gh repo deploy-key -R marc272/crc-sdk delete 123"),
    ("deny", "deny", "gh repo autolink create JIRA- https://example.com/x"),
    ("deny", "deny", "gh repo autolink new JIRA- https://example.com/x"),
    ("deny", "deny", "gh repo autolink delete 5 --yes"),
    ("deny", "deny", "gh repo autolink -R marc272/crc-sdk create JIRA- x"),
    ("deny", "deny", "gh repo autolink -R marc272/crc-sdk new JIRA- x"),
    ("deny", "deny", "gh repo autolink -R marc272/crc-sdk delete 5"),
    ("deny", "deny", "gh gist create notes.md --public"),
    ("deny", "deny", "gh gist new notes.md"),
    ("deny", "allow", "gh api -X POST repos/marc272/crc-sdk/keys -f key=x"),
    ("deny", "allow", "gh api -X POST repos/marc272/crc-sdk/autolinks -f key_prefix=x"),
    ("pass", "allow", "gh repo deploy-key list --repo marc272/crc-sdk"),
    ("pass", "allow", "gh repo autolink list -R marc272/crc-sdk"),
    ("pass", "allow", "gh gist list"),
    # MAR-289 item 6: agent tasks, gh's program settings and the token.
    ("deny", "deny", "gh agent-task create x"),
    ("deny", "deny", "gh agent-tasks create x"),
    ("deny", "deny", "gh agents create x"),
    ("deny", "deny", "gh agent create x"),
    ("deny", "deny", "gh config set editor vim"),
    ("deny", "deny", "gh config set pager less"),
    ("deny", "deny", "gh config set browser x"),
    ("deny", "deny", "gh config set -h github.com editor vim"),
    ("deny", "deny", "gh config set --host github.com pager cat"),
    ("deny", "deny", "gh config set -h github.com browser x"),
    ("deny", "deny", "gh auth token"),
    ("deny", "deny", "gh auth status --show-token"),
    ("deny", "deny", "gh auth status -a --show-token"),
    ("deny", "deny", "gh auth status -t"),
    ("pass", "deny", "gh auth status -at"),
    ("pass", "allow", "gh agent-task list"),
    ("pass", "allow", "gh config get editor"),
    ("pass", "allow", "gh config set prompt disabled"),
    ("pass", "allow", "gh auth status"),
    # MAR-289 item 6: from a variable, only the hook can tell.
    ("pass", "deny", "$GH release create v1"),
    ("pass", "deny", "$GIT push origin v1.0.0"),
    ("pass", "deny", "gh pr merge 3 $X"),
    # MAR-306: Actions stay off on crc-docs.
    (
        "deny",
        "deny",
        "gh api -X PUT repos/marc272/crc-docs/actions/permissions -F enabled=true",
    ),
    (
        "deny",
        "deny",
        "gh api --method PUT repos/marc272/crc-docs/actions/permissions"
        " -F enabled=true",
    ),
    (
        "deny",
        "deny",
        "gh api --method=PUT repos/marc272/crc-docs/actions/permissions/workflow"
        " -f default_workflow_permissions=read",
    ),
    (
        "deny",
        "deny",
        "gh api repos/marc272/crc-docs/actions/permissions -X PUT -F enabled=true",
    ),
    (
        "pass",
        "allow",
        "gh api repos/marc272/crc-docs/actions/permissions --jq .enabled",
    ),
    # The orchestrator's prescribed merges, MAR-306's --merge form included.
    (
        "pass",
        "allow",
        "gh pr merge 2 --repo marc272/crc-docs --merge"
        ' --subject "chore: merge upstream main into parametric (#2)"'
        ' --body "Refs: MAR-300"',
    ),
    (
        "pass",
        "allow",
        'gh pr merge "$N" --repo marc272/crc-sdk --squash --subject "$S" --body "$B"',
    ),
]

# --- The deny rules on other tools (MAR-282) ----------------------------------
#
# A deny rule without parentheses names a tool and removes it from Claude's
# context (permissions page, "Tool name wildcards" and "MCP", read
# 2026-11-06). ``tool_rule_matches`` models how such a rule matches a tool
# name, and ``TOOL_RULE_DOC_EXAMPLES`` checks the model against the page:
#
# - the rule is a glob that must match the whole tool name; ``*`` stands for
#   any text (``mcp__*`` is every MCP tool, ``mcp__github__get_*`` its get_
#   tools);
# - a bare ``mcp__<server>`` also matches every tool of that server, and as a
#   deny rule also of a server whose name starts with ``<server>__``;
# - an ``mcp__`` rule with parentheses is skipped when settings load, and a
#   rule matches the canonical tool name, never its label.


def tool_rule_matches(rule: str, tool: str) -> bool:
    """Whether a deny rule without a ``Bash(...)`` pattern matches a tool.

    Parameters
    ----------
    rule
        The rule, as written in ``permissions.deny``.
    tool
        A canonical tool name, e.g. ``mcp__Claude_Browser__preview_start``.

    Returns
    -------
    bool
        Whether the rule denies the whole tool.
    """
    if "(" in rule:
        return False  # a specifier rule, or an mcp__ rule that is skipped
    regex = ".*".join(re.escape(part) for part in rule.split("*"))
    if re.fullmatch(regex, tool, re.DOTALL):
        return True
    return "*" not in rule and rule.startswith("mcp__") and tool.startswith(rule + "__")


def tool_denied_by(tool: str, rules: list[str]) -> str | None:
    """Return the first deny rule that removes ``tool``, or ``None``.

    Parameters
    ----------
    tool
        A canonical tool name.
    rules
        The deny rules of a settings file.

    Returns
    -------
    str or None
        The rule, or ``None`` if none matches.
    """
    return next((rule for rule in rules if tool_rule_matches(rule, tool)), None)


# (rule, tool, matches) from the permissions page: "Tool name wildcards",
# "MCP", and the canonical-name note under "Permission rule syntax".
TOOL_RULE_DOC_EXAMPLES: list[tuple[str, str, bool]] = [
    ("*", "Bash", True),
    ("mcp__*", "mcp__puppeteer__puppeteer_navigate", True),
    ("mcp__*", "Bash", False),
    ("mcp__puppeteer", "mcp__puppeteer__puppeteer_navigate", True),
    ("mcp__puppeteer", "mcp__puppeteer_v2__puppeteer_navigate", False),
    ("mcp__puppeteer__*", "mcp__puppeteer__puppeteer_navigate", True),
    (
        "mcp__puppeteer__puppeteer_navigate",
        "mcp__puppeteer__puppeteer_navigate",
        True,
    ),
    ("mcp__puppeteer__puppeteer_navigate", "mcp__puppeteer__puppeteer_click", False),
    ("mcp__github__get_*", "mcp__github__get_issue", True),
    ("mcp__github__get_*", "mcp__github__create_issue", False),
    ("mcp__my_server__*", "mcp__my_server__query", True),
    ("mcp__reports__v2__*", "mcp__reports__v2__export", True),
    ("mcp__reports", "mcp__reports__v2__export", True),
    ("mcp__reports__v2", "mcp__reports__v2__export", True),
    ("mcp__puppeteer__puppeteer_navigate(url:*)", "mcp__puppeteer__x", False),
    ("Stop Task", "TaskStop", False),
]

# (deny rules, tool): what the deny rules of .claude/settings.json do with a
# tool ("deny" removes it, "pass" keeps it). The names are those of this
# session's tool list, except the computer-use tools (not enabled here; their
# server is mcp__computer-use) and the remote-devices tools, which a cloud
# session linked to the owner's computer has (both named as the app's skill
# descriptions give them).
TOOL_RULE_CASES: list[tuple[str, str]] = [
    # Marc's gap-3 decision on MAR-263 (MAR-282 item 1).
    ("deny", "mcp__Claude_Browser__preview_start"),
    ("deny", "mcp__Claude_Code_iOS_Simulator__build"),
    ("deny", "mcp__Claude_Code_iOS_Simulator__control"),
    ("deny", "mcp__ccd_directory__change_directory"),
    ("deny", "mcp__computer-use__screenshot"),
    ("deny", "mcp__computer-use__left_click"),
    ("deny", "mcp__remote-devices__Claude_Browser__preview_start"),
    ("deny", "mcp__remote-devices__computer_screenshot"),
    ("deny", "mcp__terminal__run_in_terminal"),
    # Kept: the rest of the Browser pane, the review-rule tools, and the
    # tools that items 5 and 6 leave to Marc.
    ("pass", "mcp__Claude_Browser__navigate"),
    ("pass", "mcp__Claude_Browser__get_page_text"),
    ("pass", "mcp__Claude_Browser__browser_batch"),
    ("pass", "mcp__Claude_Browser__preview_list"),
    ("pass", "mcp__Claude_Browser__preview_stop"),
    ("pass", "mcp__remote-devices__Claude_Browser__navigate"),
    ("pass", "mcp__ccd_directory__request_directory"),
    ("pass", "mcp__ccd_session__start_session"),
    ("pass", "mcp__scheduled-tasks__create_scheduled_task"),
    ("deny", "mcp__ccd_pr__set_auto_merge"),  # MAR-289: Marc's decision
    ("deny", "mcp__claude-in-chrome__navigate"),  # MAR-289: Marc's decision
    ("pass", "mcp__terminal__open_terminal_tab"),
    ("pass", "Bash"),
    ("pass", "Agent"),
    # MAR-289 item 2, Marc's decisions on MAR-282: the routes to a GitHub merge
    # or approval that start no process. The globs cover a renamed server. The
    # GitHub plugin isn't authenticated here, so its tool name is an example.
    ("deny", f"{LINEAR}__merge_diff"),
    ("deny", f"{LINEAR}__submit_diff_review"),
    ("deny", "mcp__plugin_engineering_linear__merge_diff"),
    ("deny", "mcp__plugin_engineering_linear__submit_diff_review"),
    ("deny", "mcp__claude-in-chrome__computer"),
    ("deny", "mcp__claude-in-chrome__javascript_tool"),
    ("deny", "mcp__plugin_engineering_github__create_pull_request"),
    # Kept: the orchestrator's own Linear use (issues, comments, status
    # updates), the rest of the diff tools and of ccd_pr, and start_session.
    ("pass", f"{LINEAR}__get_issue"),
    ("pass", f"{LINEAR}__list_issues"),
    ("pass", f"{LINEAR}__save_issue"),
    ("pass", f"{LINEAR}__list_comments"),
    ("pass", f"{LINEAR}__save_comment"),
    ("pass", f"{LINEAR}__get_project"),
    ("pass", f"{LINEAR}__get_status_updates"),
    ("pass", f"{LINEAR}__save_status_update"),
    ("pass", f"{LINEAR}__get_diff"),
    ("pass", f"{LINEAR}__list_diffs"),
    ("pass", f"{LINEAR}__update_diff"),
    ("pass", "mcp__plugin_engineering_linear__save_issue"),
    ("pass", "mcp__ccd_pr__get_status"),
    ("pass", "mcp__ccd_pr__bind_pr"),
    ("pass", "mcp__ccd_pr__set_monitor"),
]

# --- The session guard (MAR-289) ----------------------------------------------
#
# (expected, label, tool_input). "allow" passes, "refuse" names a parameter
# that would run the session somewhere else.
_FRESH: dict[str, object] = {
    "initiation": "user_asked",
    "title": "MAR-1: a piece of work",
    "prompt": "Do the piece.",
    "background": "x" * 80,
}
SESSION_CASES: list[tuple[str, str, dict[str, object]]] = [
    # What "Delegating to subagents" passes.
    ("allow", "fresh, no place fields", _FRESH),
    ("allow", "fork context", {**_FRESH, "context": "fork"}),
    ("allow", "own worktree", {**_FRESH, "use_worktree": True, "branch_name": "x"}),
    ("allow", "model, effort", {**_FRESH, "model": "m", "effort": "low"}),
    ("allow", "permission mode", {**_FRESH, "permission_mode": "auto"}),
    ("allow", "proposal_id only", {"proposal_id": "task_ab12cd34"}),
    ("allow", "an offer: title only", {"initiation": "offer", "title": "x"}),
    ("allow", 'target "local"', {**_FRESH, "target": "local"}),
    # Present but empty: not set, as the issue says.
    ("allow", 'cwd ""', {**_FRESH, "cwd": ""}),
    ("allow", "cwd null", {**_FRESH, "cwd": None}),
    ("allow", 'host ""', {**_FRESH, "host": ""}),
    ("allow", "host null", {**_FRESH, "host": None}),
    ("allow", 'preset ""', {**_FRESH, "preset": ""}),
    ("allow", 'environment ""', {**_FRESH, "environment": ""}),
    ("allow", "environment {}", {**_FRESH, "environment": {}}),
    ("allow", 'repository ""', {**_FRESH, "repository": ""}),
    ("allow", "repository []", {**_FRESH, "repository": []}),
    ("allow", 'target ""', {**_FRESH, "target": ""}),
    ("allow", "target null", {**_FRESH, "target": None}),
    # Each field that puts a session elsewhere.
    ("refuse", "cwd", {**_FRESH, "cwd": "/Users/marcprinzing/elsewhere"}),
    ("refuse", "cwd in the forks", {**_FRESH, "cwd": FORKS}),
    ("refuse", 'cwd "~"', {**_FRESH, "cwd": "~"}),
    ("refuse", "host", {**_FRESH, "host": "box"}),
    ("refuse", "preset", {**_FRESH, "preset": "saved"}),
    ("refuse", "environment", {**_FRESH, "environment": "env"}),
    ("refuse", "repository", {**_FRESH, "repository": "marc272/crc-sdk"}),
    ("refuse", 'target "cloud"', {**_FRESH, "target": "cloud"}),
    ("refuse", 'target "ssh"', {**_FRESH, "target": "ssh"}),
    # What the tool's schema pairs together.
    ("refuse", "ssh with host", {**_FRESH, "target": "ssh", "host": "box"}),
    (
        "refuse",
        "cloud with repository",
        {**_FRESH, "target": "cloud", "repository": "marc272/crc-sdk"},
    ),
    ("refuse", 'target "local" with cwd', {**_FRESH, "target": "local", "cwd": "/x"}),
    # Only "local" is local, and a set field of the wrong type still counts.
    ("refuse", 'target "LOCAL"', {**_FRESH, "target": "LOCAL"}),
    ("refuse", "target a number", {**_FRESH, "target": 3}),
    ("refuse", "target true", {**_FRESH, "target": True}),
    ("refuse", "cwd only spaces", {**_FRESH, "cwd": "  "}),
    ("refuse", "cwd 0", {**_FRESH, "cwd": 0}),
    ("refuse", "cwd false", {**_FRESH, "cwd": False}),
    ("refuse", "environment an object", {**_FRESH, "environment": {"name": "x"}}),
    ("refuse", "repository a list", {**_FRESH, "repository": ["marc272/crc-sdk"]}),
]


def run_hook(
    python: str,
    payload: object,
    env: dict[str, str],
    raw: str | None = None,
    force_error: bool = False,
    hook: Path = HOOK,
) -> subprocess.CompletedProcess[str]:
    """Run a hook once, as Claude Code does, and return the finished process.

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
    hook
        The hook to run: the fork gh guard, or ``SESSION_HOOK``.

    Returns
    -------
    subprocess.CompletedProcess
        The finished process, with its stdout and stderr.
    """
    argv = [python, "-I", str(hook)]
    if force_error:
        argv = [python, "-I", "-c", FORCE_INTERNAL_ERROR, str(hook)]
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
        ``allow`` for exit 0 with no output; for exit 2 with nothing on
        stdout and the guard's message on stderr, ``deny`` if the message
        says the command is denied in every spelling (a denied gh command,
        MAR-263), else ``refuse`` if it names the fork fix (a ``marc272/``
        repository: ``--repo marc272/<fork>``, or ``repos/marc272/<fork>``
        for gh api); otherwise a description of what went wrong.
    """
    if proc.returncode == 0 and not proc.stdout and not proc.stderr:
        return "allow"
    if (
        proc.returncode == 2
        and not proc.stdout
        and "Refused by the fork gh guard" in proc.stderr
    ):
        if DENIED_MARK in proc.stderr:
            return "deny"
        if "--repo marc272/" in proc.stderr or "repos/marc272/" in proc.stderr:
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


def session_verdict(proc: subprocess.CompletedProcess[str]) -> str:
    """Classify a run of the session guard.

    Parameters
    ----------
    proc
        A finished hook process.

    Returns
    -------
    str
        ``allow`` for exit 0 with no output; for exit 2 with nothing on
        stdout, ``refuse`` if the message names a parameter that moves the
        session and ``malformed`` if the hook couldn't check the call;
        otherwise a description of what went wrong.
    """
    if proc.returncode == 0 and not proc.stdout and not proc.stderr:
        return "allow"
    if proc.returncode == 2 and not proc.stdout and SESSION_REFUSED in proc.stderr:
        if SESSION_WOULD_MOVE in proc.stderr:
            return "refuse"
        if SESSION_MALFORMED in proc.stderr:
            return "malformed"
    return f"exit {proc.returncode}, stdout {proc.stdout!r}, stderr {proc.stderr!r}"


def session_input(tool_input: object) -> dict[str, object]:
    """Return a ``PreToolUse`` hook input for ``start_session``.

    Parameters
    ----------
    tool_input
        The tool's input.

    Returns
    -------
    dict
        The hook input.
    """
    return hook_input(REPO, SESSION_TOOL, tool_input)


def malformed_session_inputs() -> list[tuple[str, object, str | None, bool]]:
    """Return the session guard's fail-closed cases.

    Returns
    -------
    list of tuple
        ``(label, payload, raw stdin or None, force an internal error)``.
        Every one must be refused as ``malformed``.
    """
    no_tool_input = session_input({})
    del no_tool_input["tool_input"]
    no_tool_name = session_input(_FRESH)
    del no_tool_name["tool_name"]
    return [
        ("stdin that isn't JSON", None, "not json", False),
        ("empty stdin", None, "", False),
        ("truncated JSON", None, '{"tool_name": "mcp__ccd_ses', False),
        ("a JSON array", [], None, False),
        ("a JSON string", "start_session", None, False),
        ("JSON null", None, "null", False),
        ("no tool_input", no_tool_input, None, False),
        ("tool_input null", session_input(None), None, False),
        ("tool_input a list", session_input(["cwd"]), None, False),
        ("tool_input a string", session_input("cwd=/x"), None, False),
        ("no tool_name", no_tool_name, None, False),
        ("another tool", hook_input(REPO, "Bash", {"command": "ls"}), None, False),
        (
            "another session tool",
            hook_input(REPO, "mcp__ccd_session__move_to_cloud", _FRESH),
            None,
            False,
        ),
        ("internal error, a clean call", session_input(_FRESH), None, True),
    ]


def check_session_cases(
    python: str, env: dict[str, str]
) -> tuple[list[str], list[str], list[str]]:
    """Run the session guard's cases; return the report, failures and results.

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
        result of each case, ``SESSION_CASES`` first.
    """
    lines, failures, results = [], [], []
    runs: list[tuple[str, str, subprocess.CompletedProcess[str]]] = [
        (
            want,
            label,
            run_hook(python, session_input(given), env, hook=SESSION_HOOK),
        )
        for want, label, given in SESSION_CASES
    ]
    runs += [
        (
            "malformed",
            label,
            run_hook(
                python, payload, env, raw=raw, force_error=force, hook=SESSION_HOOK
            ),
        )
        for label, payload, raw, force in malformed_session_inputs()
    ]
    for n, (want, label, proc) in enumerate(runs, 1):
        got = session_verdict(proc)
        results.append(got)
        line = f"S{n:<3d}[{want}] start_session: {label}"
        if got == want:
            lines.append(f"ok   {line}")
        else:
            lines.append(f"FAIL {line}\n     got: {got}")
            failures.append(line)
    return lines, failures, results


def check_session_wiring(settings: dict[str, object], env: dict[str, str]) -> list[str]:
    """Check the session guard's wiring in a settings object; return failures.

    It must be one ``PreToolUse`` hook whose matcher is exactly
    ``SESSION_TOOL``, and its command string, run through ``sh -c`` with
    ``CLAUDE_PROJECT_DIR`` set, must allow a clean call and refuse a moved one
    and a malformed one.

    Parameters
    ----------
    settings
        A parsed settings file.
    env
        The environment of the hook process.

    Returns
    -------
    list of str
        A description of each check that failed.
    """
    hooks = settings.get("hooks", {})
    groups = hooks.get("PreToolUse", []) if isinstance(hooks, dict) else []
    found = [
        (str(group.get("matcher", "")), hook)
        for group in groups
        for hook in group.get("hooks", [])
        if "session_guard.py" in str(hook.get("command", ""))
    ]
    if len(found) != 1:
        return [f"want 1 PreToolUse hook on the session guard: {len(found)}"]
    failures = []
    matcher, hook = found[0]
    if matcher_names(matcher) != {SESSION_TOOL}:
        failures.append(f"the session guard's matcher is {matcher!r}")
    command = str(hook.get("command", ""))
    if hook.get("type") != "command" or "args" in hook:
        failures.append("the session guard must be a shell-form command hook")
    if not command.startswith("python3 -I ") or "$CLAUDE_PROJECT_DIR" not in command:
        failures.append(f"unexpected session guard command: {command}")
    if not isinstance(hook.get("timeout"), (int, float)):
        failures.append("the session guard must set a timeout")
    sh_env = {**env, "CLAUDE_PROJECT_DIR": str(ROOT)}
    for expected, given in (
        ("allow", json.dumps(session_input(_FRESH))),
        ("refuse", json.dumps(session_input({**_FRESH, "cwd": "/x"}))),
        ("malformed", "not json"),
    ):
        proc = subprocess.run(
            ["sh", "-c", command],
            input=given,
            capture_output=True,
            text=True,
            env=sh_env,
            cwd=ROOT,
            timeout=30,
            check=False,
        )
        got = session_verdict(proc)
        if got != expected:
            failures.append(f"session guard command: want {expected}, {got}")
    return failures


def check_doc_examples() -> list[str]:
    """Check ``rule_matches`` and ``denied_by`` on the docs' examples.

    Returns
    -------
    list of str
        One line per example that the model gets wrong.
    """
    failures = []
    for pattern, command, expected in DOC_RULE_EXAMPLES:
        got = denied_by(command, [pattern]) is not None
        if got != expected:
            failures.append(
                f"deny-rule model: Bash({pattern}) on {command!r}:"
                f" want {'match' if expected else 'no match'}"
            )
    for rule, tool, expected in TOOL_RULE_DOC_EXAMPLES:
        if tool_rule_matches(rule, tool) != expected:
            failures.append(
                f"tool-rule model: {rule} on {tool}:"
                f" want {'match' if expected else 'no match'}"
            )
    return failures


def check_tool_rule_cases() -> tuple[list[str], list[str], list[str]]:
    """Run every case of ``TOOL_RULE_CASES``; return the report, failures, rules.

    Returns
    -------
    tuple of list of str
        One report line per case, the lines of the failed cases, and per case
        the deny rule that matched (or ``""``).
    """
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    deny = settings.get("permissions", {}).get("deny") or []
    rules = [r for r in deny if isinstance(r, str) and not r.startswith("Bash(")]
    lines, failures, results = [], [], []
    for n, (want, tool) in enumerate(TOOL_RULE_CASES, 1):
        rule = tool_denied_by(tool, rules) or ""
        results.append(rule)
        line = f"T{n:<3d}[{want}] {tool}"
        if ("deny" if rule else "pass") == want:
            lines.append(f"ok   {line}" + (f"  ({rule})" if rule else ""))
        else:
            lines.append(f"FAIL {line}\n     got: {rule or 'pass'}")
            failures.append(line)
    return lines, failures, results


def check_rule_cases(
    python: str, env: dict[str, str]
) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """Run every case of ``RULE_CASES``; return the report, failures, results.

    Each command goes through the Bash deny rules of ``.claude/settings.json``
    (``denied_by``) and through the hook, from this repository's main
    checkout.

    Parameters
    ----------
    python
        The interpreter to run the hook with.
    env
        The environment of the hook process.

    Returns
    -------
    tuple
        One report line per case, the lines of the failed cases, and per
        case the deny rule that matched (or ``""``) and the hook's result.
    """
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    patterns = bash_deny_patterns(settings)
    lines, failures, results = [], [], []
    for n, (rules_want, hook_want, command) in enumerate(RULE_CASES, 1):
        rule = denied_by(command, patterns) or ""
        rules_got = "deny" if rule else "pass"
        hook_got = verdict(run_hook(python, bash_input(REPO, command), env))
        results.append((rule, hook_got))
        line = f"R{n:<3d}[rules {rules_want}, hook {hook_want}] {command}"
        if rules_got == rules_want and hook_got == hook_want:
            lines.append(f"ok   {line}" + (f"  ({rule})" if rule else ""))
        else:
            got = f"rules {rule or 'pass'}, hook {hook_got}"
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
            "deny",  # MAR-282: a rerun in a fork path (refused until then)
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
        # MAR-263: a failure also refuses what looks like a denied gh command.
        (
            "refuse",
            "internal error: gh repo new crc-scratch, this repo",
            bash_input(REPO, "gh repo new crc-scratch"),
            None,
            True,
        ),
        (
            "refuse",
            "internal error: gh -R marc272/crc-sdk workflow run x, this repo",
            bash_input(REPO, "gh -R marc272/crc-sdk workflow run release.yaml"),
            None,
            True,
        ),
        (
            "allow",  # MAR-282: was gh repo view, which is a checked command now
            "internal error: gh repo list marc272, this repo",
            bash_input(REPO, "gh repo list marc272"),
            None,
            True,
        ),
        # MAR-282: and the new checked and denied commands.
        (
            "refuse",
            "internal error: gh repo view marc272/crc-sdk, this repo",
            bash_input(REPO, "gh repo view marc272/crc-sdk"),
            None,
            True,
        ),
        (
            "refuse",
            "internal error: gh alias set rc 'release create', this repo",
            bash_input(REPO, "gh alias set rc 'release create'"),
            None,
            True,
        ),
        (
            "refuse",
            "internal error: gh $c create v1, this repo",
            bash_input(REPO, "gh $c create v1"),
            None,
            True,
        ),
        (
            "refuse",
            "internal error: gh run rerun 3 --repo marc272/crc-sdk, this repo",
            bash_input(REPO, "gh run rerun 3 --repo marc272/crc-sdk"),
            None,
            True,
        ),
        (
            "allow",
            "internal error: gh alias list && gh skill list, this repo",
            bash_input(REPO, "gh alias list && gh skill list"),
            None,
            True,
        ),
        (
            "deny",
            "Monitor, this repo: gh run watch 9 && gh run rerun 9 -R marc272/crc-sdk",
            monitor_input(REPO, "gh run watch 9 && gh run rerun 9 -R marc272/crc-sdk"),
            None,
            False,
        ),
        (
            "refuse",
            "terminal tool, cwd forks/crc-sdk: gh repo view",
            terminal_input(REPO, "gh repo view", SDK),
            None,
            False,
        ),
        (
            "deny",
            "Monitor, this repo: gh -R marc272/crc-sdk release create v1",
            monitor_input(REPO, "gh -R marc272/crc-sdk release create v1"),
            None,
            False,
        ),
        (
            "deny",
            "terminal tool, cwd this repo: gh release new v1",
            terminal_input(REPO, "gh release new v1", REPO),
            None,
            False,
        ),
        # MAR-289: the git checks on the other tools, and when the hook fails.
        (
            "deny",
            "Monitor, this repo: git push origin v1.0.0",
            monitor_input(REPO, "git push origin v1.0.0"),
            None,
            False,
        ),
        (
            "deny",
            "terminal tool, cwd forks/crc-sdk: git tag v1.0.0",
            terminal_input(REPO, "git tag v1.0.0", SDK),
            None,
            False,
        ),
        (
            "refuse",
            "internal error: git tag v1.0.0, this repo",
            bash_input(REPO, "git tag v1.0.0"),
            None,
            True,
        ),
        (
            "refuse",
            "internal error: git push origin v1.0.0, this repo",
            bash_input(REPO, "git push origin v1.0.0"),
            None,
            True,
        ),
        (
            "refuse",
            "internal error: git push --mirror origin, this repo",
            bash_input(REPO, "git push --mirror origin"),
            None,
            True,
        ),
        (
            "refuse",
            "internal error: git update-ref refs/tags/v1 HEAD, this repo",
            bash_input(REPO, "git update-ref refs/tags/v1 HEAD"),
            None,
            True,
        ),
        (
            "allow",
            "internal error: git push -u origin marcprinzing/x, this repo",
            bash_input(REPO, "git push -u origin marcprinzing/x"),
            None,
            True,
        ),
        (
            "allow",
            'internal error: git commit -m "tag v1", this repo',
            bash_input(REPO, 'git commit -m "tag v1"'),
            None,
            True,
        ),
        (
            "refuse",
            "internal error: gh gist create notes.md, this repo",
            bash_input(REPO, "gh gist create notes.md"),
            None,
            True,
        ),
        (
            "refuse",
            "internal error: gh repo deploy-key add key.pub, this repo",
            bash_input(REPO, "gh repo deploy-key add key.pub"),
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


def tool_rule_problems(deny: list[object]) -> list[str]:
    """Return the deny rules that aren't Bash rules or bare ``mcp__`` names.

    Settings skip an ``mcp__`` rule with parentheses, and a tool name without
    ``_`` or ``*`` that matches no tool draws a startup warning (permissions
    page). Every deny rule here is a ``Bash(...)`` rule or a bare ``mcp__``
    name or glob, which has a ``_`` and so draws none, even while its server
    is off.

    Parameters
    ----------
    deny
        The ``permissions.deny`` list of a settings file.

    Returns
    -------
    list of str
        One line per rule of another form.
    """
    problems = []
    for rule in deny:
        if isinstance(rule, str) and rule.startswith("Bash("):
            continue
        if not isinstance(rule, str) or not rule.startswith("mcp__") or "(" in rule:
            problems.append(
                f"deny rule {rule!r}: want Bash(...) or a bare mcp__ tool name"
                " (settings skip mcp__ rules with parentheses)"
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
    for rule in (
        *GH_REPO_DENY_RULES,
        TERMINAL_TOOL,
        *APP_TOOL_DENY_RULES,
        *MERGE_ROUTE_DENY_RULES,
    ):
        if rule not in deny:
            failures.append(f"settings.json lacks the deny rule {rule}")
    failures += tool_rule_problems(deny)
    failures += check_session_wiring(settings, env)
    probes: list[object] = ["mcp__ccd_session__start_session(cwd:*)", "Fetch"]
    if len(tool_rule_problems(probes)) != len(probes):
        failures.append("the tool-rule check doesn't fire on its probes")
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
        ("deny", bash_input(REPO, "gh -R marc272/crc-sdk release create v1")),
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
    """Check that the hooks parse with Python 3.9's grammar; return failures.

    Returns
    -------
    list of str
        The syntax errors, if any.
    """
    failures = []
    for hook in (HOOK, SESSION_HOOK):
        try:
            ast.parse(hook.read_text(encoding="utf-8"), feature_version=(3, 9))
        except SyntaxError as exc:
            failures.append(f"{hook.name} needs a Python newer than 3.9: {exc}")
    return failures


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
    rows = [
        "| # | Starts in | Command | Expected | Result |",
        "|---|---|---|---|---|",
    ]
    pairs = zip(CASES, results, strict=True)
    for n, ((expected, cwd, command), got) in enumerate(pairs, 1):
        label = CWD_LABELS.get(cwd, cwd)
        result = f"**{got}**" if got == expected else f"FAIL: {got}"
        rows.append(f"| {n} | {label} | {_code(command)} | {expected} | {result} |")
    return "\n".join(rows)


def _code(text: str) -> str:
    """Return ``text`` as Markdown inline code, ``WS`` shown as ``<WS>``."""
    text = text.replace(WS, "<WS>").replace("\n", "\\n").replace("|", "\\|")
    return f"`` {text} ``" if "`" in text else f"`{text}`"


def markdown_rule_table(results: list[tuple[str, str]]) -> str:
    """Return the cases of ``RULE_CASES`` and their results as a table.

    Parameters
    ----------
    results
        Per case, the deny rule that matched (or ``""``) and the hook's
        result, in the order of ``RULE_CASES``.

    Returns
    -------
    str
        A table with the number, command, what the deny rules and the hook
        were expected to do and did, and the rule that matched.
    """
    rows = [
        "| # | Command | Deny rules | Hook | Matching rule |",
        "|---|---|---|---|---|",
    ]
    pairs = zip(RULE_CASES, results, strict=True)
    for n, ((rules_want, hook_want, command), (rule, hook_got)) in enumerate(pairs, 1):
        rules_got = "deny" if rule else "pass"
        rules = f"**{rules_got}**" if rules_got == rules_want else f"FAIL: {rules_got}"
        hook = f"**{hook_got}**" if hook_got == hook_want else f"FAIL: {hook_got}"
        shown = _code(rule) if rule else ""
        rows.append(f"| R{n} | {_code(command)} | {rules} | {hook} | {shown} |")
    return "\n".join(rows)


def markdown_tool_rule_table(results: list[str]) -> str:
    """Return the cases of ``TOOL_RULE_CASES`` and their results as a table.

    Parameters
    ----------
    results
        Per case, the deny rule that matched (or ``""``), in the order of
        ``TOOL_RULE_CASES``.

    Returns
    -------
    str
        A table with the number, tool, what the deny rules were expected to
        do and did, and the rule that matched.
    """
    rows = ["| # | Tool | Deny rules | Matching rule |", "|---|---|---|---|"]
    pairs = zip(TOOL_RULE_CASES, results, strict=True)
    for n, ((want, tool), rule) in enumerate(pairs, 1):
        got = "deny" if rule else "pass"
        shown = f"**{got}**" if got == want else f"FAIL: {got}"
        rows.append(f"| T{n} | `{tool}` | {shown} | {_code(rule) if rule else ''} |")
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


def markdown_session_table(results: list[str]) -> str:
    """Return the session guard's cases and their results as a table.

    Parameters
    ----------
    results
        The result of each case, ``SESSION_CASES`` first, then
        ``malformed_session_inputs()``.

    Returns
    -------
    str
        A table with the number, case, expectation and result of each case.
    """
    rows = ["| # | Call | Expected | Result |", "|---|---|---|---|"]
    expected = [(want, label) for want, label, _ in SESSION_CASES]
    expected += [("malformed", case[0]) for case in malformed_session_inputs()]
    for n, ((want, label), got) in enumerate(zip(expected, results, strict=True), 1):
        result = f"**{got}**" if got == want else f"FAIL: {got}"
        rows.append(f"| S{n} | {label} | {want} | {result} |")
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
    rule_lines, rule_failures, rule_results = check_rule_cases(args.python, env)
    print("\n".join(rule_lines))
    failures += rule_failures
    tool_lines, tool_failures, tool_results = check_tool_rule_cases()
    print("\n".join(tool_lines))
    failures += tool_failures
    session_lines, session_failures, session_results = check_session_cases(
        args.python, env
    )
    print("\n".join(session_lines))
    failures += session_failures
    for problem in check_settings(env) + check_grammar() + check_doc_examples():
        print(f"FAIL {problem}")
        failures.append(problem)
    if args.markdown:
        print()
        print(markdown_table(results))
        print()
        print(markdown_input_table(input_results))
        print()
        print(markdown_rule_table(rule_results))
        print()
        print(markdown_tool_rule_table(tool_results))
        print()
        print(markdown_session_table(session_results))
    version = subprocess.run(
        [args.python, "--version"], capture_output=True, text=True, check=False
    ).stdout.strip()
    per_case = 1000 * elapsed / len(CASES)
    print(
        f"check_fork_gh_guard: {len(CASES)} cases on {version},"
        f" {per_case:.0f} ms per hook call; {len(RULE_CASES)} deny-rule cases"
        f" and {len(DOC_RULE_EXAMPLES)} docs examples; {len(TOOL_RULE_CASES)}"
        f" tool-rule cases and {len(TOOL_RULE_DOC_EXAMPLES)} docs examples;"
        f" {len(session_results)} session-guard cases"
    )
    if failures:
        print(f"check_fork_gh_guard: FAILED, {len(failures)} problem(s) (see above)")
        return 1
    print("check_fork_gh_guard: all cases and checks as expected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
