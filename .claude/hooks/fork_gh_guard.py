#!/usr/bin/env python3
"""Refuse repo-scoped ``gh`` commands in the CRC forks without ``--repo marc272/``.

A Claude Code ``PreToolUse`` hook (MAR-253, MAR-261, MAR-263, MAR-282,
MAR-289), wired in ``.claude/settings.json`` on the tools that run shell
commands: ``Bash``, ``Monitor`` and the desktop app's terminal tool
(``mcp__terminal__run_in_terminal``). It adds three checks to the deny rules
in ``.claude/settings.json``, which match the command text and so miss some
spellings.

**Tags through git, in every spelling, wherever they run** (MAR-289). A
pushed ``v*`` tag runs crc-sdk's Package release. The hook parses each ``git``
command, so ``git`` by path or in quotes, ``-C`` and ``-c`` before the
subcommand, quotes around a refspec, a URL as the remote and ``sh -c`` don't
hide it (``GitInvocation.denied``). It refuses:

- ``git tag``, and ``git update-ref`` on ``refs/tags`` or with ``--stdin``;
- ``git push`` with ``--tags``, ``--follow-tags`` or ``--mirror`` (abbreviated
  too), the word ``tag``, a refspec with ``refs/tags`` or ``tags/``, or a
  refspec whose source or destination starts with ``v``, and ``git send-pack``
  and ``http-push``; a bare name is judged by its text, because only the name
  of a ``v*`` tag can start the release;
- ``git push`` with ``--all``, ``--branches`` or ``--prune`` (abbreviated too)
  or the matching refspec (``:``, ``+:``), MAR-343: the first three kinds push
  a local ``main`` and ``parametric``, and ``--prune`` deletes remote branches;
- ``git push`` whose destination is ``main`` or ``parametric`` (MAR-355), named
  as the bare branch, ``heads/<name>``, ``refs/heads/<name>``, ``<src>:<name>``
  or ``<name>:``, a force or a delete included. ``git push`` alone and ``git
  push origin HEAD`` name no branch and pass (``_names_shared_branch``);
- configuration that makes a plain push carry tags or every matching branch,
  or adds a git command: ``push.followTags``, ``push.default``,
  ``remote.<name>.push``, ``remote.<name>.mirror`` and ``alias.<name>``, set
  with ``-c``, ``--config-env`` or ``git config``, and ``git remote add
  --mirror``;
- configuration from the environment (MAR-343): a command's leading
  assignment to, or ``env`` or ``export`` of, ``GIT_CONFIG_COUNT``,
  ``GIT_CONFIG_KEY_<n>``, ``GIT_CONFIG_VALUE_<n>``, ``GIT_CONFIG_PARAMETERS``,
  ``GIT_CONFIG_GLOBAL``, ``GIT_CONFIG_SYSTEM`` or ``GIT_CONFIG``, and ``git
  submodule foreach``, which runs a shell string the hook doesn't read;
- ``git credential`` and the ``git credential-<helper>`` commands (MAR-355),
  which can print the token that ``gh auth token`` would;
- ``git rebase --exec`` (``-x``, abbreviated or in a cluster too) and ``git
  filter-branch`` (MAR-355), which run shell strings the hook doesn't read;
- a subcommand, configuration key, ``git update-ref`` ref, ``git push``
  operand or flag name, or ``git rebase`` flag name that the shell expands.
  The prescribed ``git -C <worktree> push -u origin <branch>`` passes, also
  with ``-C "$WT"``.

**Denied gh commands, in every spelling, wherever they run** (MAR-263). The
hook parses each ``gh`` command, so ``-R``/``--repo`` before or after the
group (``gh -R <repo> release create``, ``gh release -R <repo> create``),
``gh`` by path or in quotes, a group's alias (``gh ext``), and ``gh`` inside
``sh -c`` don't hide it. It refuses these, with a message that says no
``--repo`` makes them allowed:

- ``gh release create`` (alias ``new``), ``edit``, ``upload``, ``delete`` and
  ``delete-asset``; ``gh workflow run``, ``enable`` and ``disable``; ``gh repo
  create`` (alias ``new``), ``delete``, ``edit``, ``fork``, ``sync``,
  ``archive``, ``unarchive`` and ``rename``; ``gh alias set`` and ``import``;
  ``gh extension install``; ``gh skill install`` (alias ``add``), ``update``
  and ``publish`` (``DENIED_COMMANDS``, MAR-282 for the last four groups);
  ``gh gist create`` (alias ``new``), ``gh agent-task create`` and ``gh auth
  token`` (MAR-289); ``gh gist edit``, ``rename`` and ``delete``, and ``gh
  auth login``, ``logout``, ``refresh``, ``switch``, ``setup-git`` and
  ``git-credential`` (MAR-343); ``gh auth status`` showing the token, and
  ``gh copilot`` (``DENIED_GROUPS``);
- ``gh repo deploy-key add`` and ``delete``, ``gh repo autolink create``
  (alias ``new``) and ``delete``, and ``gh config set editor``, ``pager`` and
  ``browser`` (``DENIED_ACTIONS``, MAR-289);
- ``gh pr merge`` with ``--admin`` or ``--admin=<value>``;
- any ``gh`` command with ``riskthinking/`` or ``github.com/riskthinking`` in
  an argument, in any case, and ``gh api`` with ``riskthinking`` anywhere in
  its arguments (the deny rules' RiskThinking forms). An inline PR body that
  names a RiskThinking repository counts: pass bodies with ``--body-file``;
- a ``gh`` command whose subcommand, or the command of a group in
  ``LITERAL_COMMAND_GROUPS``, is a word the shell expands (``gh $c …``,
  ``gh release "$x" …``, ``gh release cre{ate,} …``): neither the rules nor
  the hook can tell what it runs (MAR-282). ``gh`` as a plain word followed
  by an expansion (``grep gh "$f"``) is refused too;
- ``gh`` itself from an expansion, when the words after it are a denied
  command (``$GH release create v1``), and an expansion among ``gh pr
  merge``'s flags (``gh pr merge 3 $X``), which could be ``--admin`` (MAR-289);
- ``gh run rerun`` of a run in a fork (a repo flag that names ``crc-sdk`` or
  ``crc-docs`` or isn't literal, or none in a fork path), and a ``gh api``
  rerun endpoint there (MAR-282): a rerun of crc-sdk's release run publishes;
- a ``gh api`` write to ``actions/permissions`` of crc-docs (MAR-306), where
  Actions stay off, or of crc-sdk (MAR-343), where they are the merge gate.
  Reading it passes.

The other ``gh api`` deny rules (``dispatches``, ``git/refs``, ``gists``,
workflow ``enable`` and ``disable`` and the like) are left to the text rules:
``gh api`` takes no ``-R``.

**Repo-scoped gh commands in a fork path.** In a clone of the forks
``marc272/crc-sdk`` and ``marc272/crc-docs``, ``gh`` without ``--repo`` can
resolve to the parent repository, RiskThinking's, where agents must never
act. A command that may run in a fork path is refused, with a message that
says how to fix it, if it runs:

- a command of a ``gh`` group that takes the repository from the clone
  unless ``--repo`` or ``-R`` names one (``REPO_FLAG_SUBCOMMANDS``: the groups
  with a group-level ``-R`` in gh 2.103.2, ``browse``, ``cache``, ``co``,
  ``discussion``, ``issue``, ``label``, ``pr``, ``release``, ``ruleset``
  (alias ``rs``), ``run``, ``secret``, ``variable`` and ``workflow``), or one
  of the other commands that have their own ``-R`` and do the same
  (``REPO_FLAG_COMMANDS``, MAR-282: ``gh agent-task create`` and ``view``,
  ``gh project link`` and ``unlink``, ``gh repo autolink``, ``deploy-key``,
  ``read-dir`` and ``read-file``), without naming a ``marc272/`` repository
  with ``--repo`` or ``-R``, written literally; ``gh`` from a variable counts
  when it stands where a program does (``$GH pr list``, MAR-343), but ``run``
  and ``cache`` only with one of gh's own commands after them, as ``$UV run
  pytest`` is no gh command;
- ``gh repo view`` without a literal ``marc272/`` repository as its argument
  (it has no ``-R``);
- ``gh api`` with ``{owner}``, ``{repo}``, ``:owner`` or ``:repo`` in its
  endpoint or a ``-F`` field, which gh fills in from the clone's repository.
  ``gh api`` has no ``--repo``: the repository must be written out.

A command may run in a fork path when any of these holds. Paths are compared
case-insensitively (macOS), and symlinks are resolved, under ``FORKS_ROOT``:

- the call starts there (the ``cwd`` of the hook input, or for the terminal
  tool its own ``cwd``, see ``terminal_starts``);
- a ``cd``, ``pushd`` or ``popd`` in the command goes there, or somewhere the
  hook can't resolve (``cd -``, ``popd``, a variable other than ``$HOME``, a
  command substitution, a glob);
- ``git -C``, ``--git-dir``, ``--work-tree``, ``GIT_DIR=`` or
  ``GIT_WORK_TREE=`` points there, or somewhere the hook can't resolve;
- ``GH_REPO`` is assigned in the command (only an explicit flag counts);
- any other word of the command, outside the arguments of ``gh`` itself,
  names a path there (e.g. ``env -C <fork>``).

The command is split at ``&&``, ``||``, ``;``, ``|``, ``&``, newlines and
parentheses. A ``cd`` adds a possible working directory and never removes
one, because it may run in a subshell, a pipeline or a branch that isn't
taken. Commands inside ``$(...)``, backticks, ``<(...)``, ``sh -c``/``bash -c``
/``zsh -c`` strings and ``eval`` are checked too; comments and here-document
bodies are skipped. ``gh`` counts wherever it appears as a word, so
``xargs gh pr view`` and ``timeout 60 gh pr checks`` are checked. A command
the hook can't parse (an unterminated quote, for example) is refused when its
text looks like a denied gh or git command (``_GH_DENIED``, ``_GIT_DENIED``),
and when it mentions ``gh`` followed by a checked subcommand (``_GH_CHECKED``)
and may touch a fork. Everything else passes: the hook prints nothing and
exits 0.

If the hook itself fails (input that isn't the documented JSON, or an
exception), it refuses a command that mentions ``gh`` followed by a checked
subcommand in the same simple command, or that looks like a denied gh or git
command, and lets every other command through.
If ``python3`` is missing, the hook can't start: Claude Code treats that as a
non-blocking error and runs the command.

Contract (Claude Code hooks reference): the hook reads the ``PreToolUse`` JSON
on stdin (``tool_name``, ``tool_input``, ``cwd``) and refuses a call by
exiting 2 with the reason on stderr, which Claude sees. It never exits with
another code. ``tool_input.command`` is the shell command of all three tools;
a ``Monitor`` WebSocket watch (``tool_input.ws``) runs none and passes. On
Claude Code v2.1.314 or later a ``Bash`` matcher also runs the hook on
``Monitor`` commands, as Bash calls; a matcher that names ``Monitor`` gets the
Monitor call's own input. The hook needs only the standard library and runs
on Python 3.9 or later (macOS's ``/usr/bin/python3``), as ``python3 -I``. Its
tests are ``scripts/check_fork_gh_guard.py``.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field

FORKS_ROOT = "/Users/marcprinzing/Parametric_Insurance/forks"
OWNER = "marc272"
# gh's aliases of command groups (gh help reference, gh 2.103.2). A group is
# known by its own name here, whichever name the command uses (MAR-282).
GROUP_ALIASES = {
    "agent": "agent-task",
    "agent-tasks": "agent-task",
    "agents": "agent-task",
    "at": "attestation",
    "cs": "codespace",
    "ext": "extension",
    "extensions": "extension",
    "rs": "ruleset",
    "skills": "skill",
}
# gh command groups that act on the clone's repository unless --repo or -R
# names one (MAR-253, MAR-261, MAR-263): the groups whose `gh <group> --help`
# lists a group-level -R in gh 2.103.2 (co is gh's default alias for
# pr checkout). Every command of a group is checked, reads included.
REPO_FLAG_SUBCOMMANDS = frozenset(
    {
        "browse",
        "cache",
        "co",
        "discussion",
        "issue",
        "label",
        "pr",
        "release",
        "ruleset",
        "run",
        "secret",
        "variable",
        "workflow",
    }
)
# gh api has no --repo; it is checked for repository placeholders instead.
CHECKED_SUBCOMMANDS = REPO_FLAG_SUBCOMMANDS | {"api"}
# Commands of other groups that have their own -R and also take the clone's
# repository without it (MAR-282): checked in fork paths like the groups
# above. gh repo view takes the repository as an argument instead (see
# GhInvocation.safe).
REPO_FLAG_COMMANDS = {
    "agent-task": frozenset({"create", "view"}),
    "project": frozenset({"link", "unlink"}),
    "repo": frozenset({"autolink", "deploy-key", "read-dir", "read-file"}),
}
# gh repo view's flags that take a value (gh repo view --help, gh 2.103.2).
REPO_VIEW_VALUE_FLAGS = frozenset(
    {"-b", "--branch", "-q", "--jq", "--json", "-t", "--template"}
)
# gh writes that the deny rules in .claude/settings.json refuse, by group and
# command, refused here in every spelling (MAR-263, MAR-282). gh release new,
# gh repo new and gh skill add are aliases of create and install (gh help
# reference, gh 2.103.2). gh skill publish creates a tag and a release.
DENIED_COMMANDS = {
    "release": frozenset({"create", "new", "edit", "upload", "delete", "delete-asset"}),
    "workflow": frozenset({"run", "enable", "disable"}),
    "repo": frozenset(
        {
            "create",
            "new",
            "delete",
            "edit",
            "fork",
            "sync",
            "archive",
            "unarchive",
            "rename",
        }
    ),
    "alias": frozenset({"set", "import"}),
    "extension": frozenset({"install"}),
    "skill": frozenset({"install", "add", "update", "publish"}),
    "gist": frozenset({"create", "new", "edit", "rename", "delete"}),
    "agent-task": frozenset({"create"}),
    "auth": frozenset(
        {
            "token",
            "login",
            "logout",
            "refresh",
            "switch",
            "setup-git",
            "git-credential",  # hidden: what setup-git wires in; prints the token
        }
    ),
}
# gh groups denied as a whole (MAR-282): gh copilot runs the Copilot CLI.
DENIED_GROUPS = frozenset({"copilot"})
# gh writes one level further down (MAR-289), by group, command and the first
# operand after it: a write deploy key is a new push credential, an autolink a
# repository setting, and gh later runs the program these config keys name.
DENIED_ACTIONS = {
    ("repo", "deploy-key"): frozenset({"add", "delete"}),
    ("repo", "autolink"): frozenset({"create", "new", "delete"}),
    ("config", "set"): frozenset({"editor", "pager", "browser"}),
}
# Flags of the commands in DENIED_ACTIONS that take a value (--help, gh 2.103.2).
ACTION_VALUE_FLAGS = frozenset({"-h", "--host"})
# Groups whose command word must be written out (MAR-282): a command taken
# from an expansion could be one of the denied ones, or a rerun.
LITERAL_COMMAND_GROUPS = frozenset(
    {*DENIED_COMMANDS, "pr", "run", "config", *REPO_FLAG_COMMANDS}
)
# gh pr merge's flags that take a value (gh pr merge --help, gh 2.103.2): an
# expansion there can't become --admin as a flag of its own (MAR-289).
PR_MERGE_VALUE_FLAGS = frozenset(
    {
        "-A",
        "--author-email",
        "-b",
        "--body",
        "-F",
        "--body-file",
        "--match-head-commit",
        "-R",
        "--repo",
        "-t",
        "--subject",
    }
)
# Groups of gh that other programs have too (uv run, uv cache, pip cache):
# after a variable, only gh's own commands count (MAR-343), so that $UV run
# pytest doesn't look like gh run.
AMBIGUOUS_GROUP_COMMANDS = {
    "run": frozenset(
        {"cancel", "delete", "download", "list", "ls", "rerun", "view", "watch"}
    ),
    "cache": frozenset({"delete", "list", "ls"}),
}
# What a word after an expansion must name to count as gh run from a variable
# (MAR-289), so that $PY tools/x.py RiskThinking/crc-sdk doesn't.
GH_GROUPS = frozenset(
    {
        *CHECKED_SUBCOMMANDS,
        *DENIED_COMMANDS,
        *DENIED_GROUPS,
        *REPO_FLAG_COMMANDS,
        *(group for group, _ in DENIED_ACTIONS),
    }
)
FORK_REPOS = re.compile(r"crc-(?:sdk|docs)", re.IGNORECASE)
# git options before the subcommand that take a separate value (git --help,
# git 2.50); -c and --config-env, which set configuration, are read apart.
GIT_VALUE_OPTIONS = frozenset(
    {"-C", "--git-dir", "--work-tree", "--namespace", "--attr-source"}
)
# git push's flags that take a separate value (git push -h, git 2.50).
GIT_PUSH_VALUE_FLAGS = frozenset(
    {
        "-o",
        "--push-option",
        "--repo",
        "--exec",
        "--receive-pack",
        "--recurse-submodules",
    }
)
# git push's flags that send tags, each with the shortest abbreviation git
# accepts for it (parse-options takes any unique prefix).
GIT_PUSH_TAG_FLAGS = (("--mirror", 3), ("--tags", 4), ("--follow-tags", 5))
# git push's flags that reach every branch, abbreviated the same way (MAR-343):
# --all and --branches push a local main and parametric too, and --prune
# deletes the remote's branches that have no local counterpart.
GIT_PUSH_EVERY_BRANCH_FLAGS = (("--all", 4), ("--branches", 3), ("--prune", 5))
# The branches that change only through merged PRs, as a git push destination
# may name them (MAR-355): git takes heads/main for refs/heads/main.
_SHARED_BRANCH = re.compile(r"(?:(?:refs/)?heads/)?(?:main|parametric)")
# git rebase's flag that runs a shell string after each commit, abbreviated the
# same way (MAR-355): --e is also --edit-todo and --empty.
GIT_REBASE_EXEC_FLAGS = (("--exec", 4),)
# -x in a cluster of short flags. Only flags that take no value may come before
# it: -Xx is a strategy option, and -Sx, -sx, -Cx and -rx give those flags a value.
_REBASE_SHORT_EXEC = re.compile(r"-[fikmnqv]*x")
# The plumbing under git push: it takes refspecs and --mirror of its own.
GIT_PUSH_PLUMBING = frozenset({"send-pack", "http-push"})
# Commands that add operands the hook can't see to the command they run.
ARGUMENT_FEEDERS = frozenset({"xargs", "parallel"})
# Configuration that makes a plain git push carry tags or every matching branch
# (push.default=matching, MAR-343), or adds a git command.
GIT_TAG_CONFIG = re.compile(
    r"push\.followtags|push\.default|remote\..+\.(?:push|mirror)|alias\..+"
)
# git config forms that only read.
GIT_CONFIG_READ_FLAGS = frozenset(
    {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "-l", "--list"}
)
GIT_CONFIG_READ_VERBS = frozenset({"get", "list"})
RISKTHINKING = "riskthinking"
# The tools whose input carries a shell command (tool_input.command).
SHELL_TOOLS = frozenset({"Bash", "Monitor"})
TERMINAL_TOOL = "mcp__terminal__run_in_terminal"
SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
LOCATION_VARIABLES = frozenset({"GIT_DIR", "GIT_WORK_TREE"})
MAX_DEPTH = 8
MAX_CWDS = 64

# Words that may come before a command word without being the command.
_KEYWORDS = frozenset(
    {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "time"}
)
_PRECOMMANDS = frozenset({"builtin", "command", "nocorrect", "noglob"})
# Commands that put a variable in the environment of what runs next (MAR-343).
_ENVIRONMENT_SETTERS = frozenset(
    {"env", "export", "declare", "typeset", "readonly", "local"}
)
# Commands that run the words after them, and a timeout's duration (MAR-343).
_WRAPPERS = frozenset(
    {*ARGUMENT_FEEDERS, "env", "exec", "nice", "nohup", "stdbuf", "timeout"}
)
_DURATION = re.compile(r"[0-9.]+[smhd]?")
_SEPARATORS = ("&&", "||", ";;", ";&", "|&", ";", "|", "&")
_REDIRECTS = ("&>>", "<<<", "<<-", "&>", ">>", ">&", "<&", ">|", "<>", "<<", ">", "<")
_ANSI_C = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "a": "\a",
    "b": "\b",
    "e": "\x1b",
    "E": "\x1b",
    "f": "\f",
    "v": "\v",
    "\\": "\\",
    "'": "'",
    '"': '"',
    "?": "?",
}
_ASSIGNMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", re.DOTALL)
_HOME_VARIABLE = re.compile(r"\$HOME(?![A-Za-z0-9_])|\$\{HOME\}")
_UNRESOLVABLE = re.compile(r"[$`*?\[{]")
_OWNER_REPO = re.compile(
    r"(?:(?:https?://)?(?:www\.)?github\.com/)?" + OWNER + r"/[A-Za-z0-9._-]+/?",
    re.IGNORECASE,
)
# gh api fills these in from the clone's repository, in its endpoint and in
# -F/--field values (gh api --help; gh still accepts the older :owner form).
_API_PLACEHOLDER = re.compile(r"\{(?:owner|repo)\}|:(?:owner|repo)\b")
# The REST endpoints that rerun a workflow run or job (MAR-282).
_API_RERUN = re.compile(r"actions/(?:runs|jobs)/[^/\s]+/rerun", re.IGNORECASE)
# The REST endpoints that turn a repository's Actions on or off (MAR-306,
# MAR-343).
_API_ACTIONS_PERMISSIONS = re.compile(r"actions/permissions", re.IGNORECASE)
# gh api sends POST when one of these is given and -X isn't (gh api --help).
_API_BODY_FLAGS = frozenset({"-f", "--raw-field", "-F", "--field", "--input"})
# A word the shell expands: a parameter, a command substitution, a glob or a
# brace pattern (gh release cre{ate,} runs gh release create cre).
_EXPANSION = re.compile(r"[$`*?\[{]")
_SHELL_VALUE = re.compile(r"[$`]")
# gh api flags whose values gh never fills in: raw fields, headers, output
# filters (a jq filter such as '{repo}' is not a placeholder) and the like.
_API_LITERAL_FLAGS = frozenset(
    {
        "-H",
        "--header",
        "-X",
        "--method",
        "-f",
        "--raw-field",
        "--input",
        "-q",
        "--jq",
        "-t",
        "--template",
        "--hostname",
        "-p",
        "--preview",
        "--cache",
    }
)
# ``cd -``, ``cd +2``: the directory stack. A bare ``-`` or digit is a cd alias
# in zsh setups such as oh-my-zsh.
_DIR_STACK = re.compile(r"-|[+-][0-9]+")
_BARE_CD = re.compile(r"-|[1-9]")
# Only for a command the hook can't parse, or when the hook fails: the word gh
# followed by a checked subcommand within one simple command (a line
# continuation allowed), so that `gh --version && uv run pytest` still passes.
# A subcommand word can't follow -, a word character, . or / (not --repo).
_SAME_COMMAND = r"(?:[^;&|\n()`]|\\\n)*?"
_WORD = r"(?<![-\w./])"


def _words(names: frozenset[str]) -> str:
    return "(?:" + "|".join(sorted(names)) + r")\b"


def _group(*groups: str) -> str:
    """Return a pattern for the words of ``groups``, their aliases included."""
    names = set(groups) | {a for a, g in GROUP_ALIASES.items() if g in groups}
    return _WORD + _words(frozenset(names))


def _group_commands(group: str, commands: frozenset[str]) -> str:
    return _group(group) + _SAME_COMMAND + _WORD + _words(commands)


_GH_CHECKED = re.compile(
    r"\bgh\b"
    + _SAME_COMMAND
    + "(?:"
    + "|".join(
        [
            _group(*CHECKED_SUBCOMMANDS),
            *(_group_commands(g, c) for g, c in sorted(REPO_FLAG_COMMANDS.items())),
            _group_commands("repo", frozenset({"view"})),
        ]
    )
    + ")"
)
# The same, for the denied gh commands (DENIED_COMMANDS, DENIED_GROUPS, an
# admin merge, a rerun that names a fork, a RiskThinking repository), in any
# case, and gh followed by an expansion.
_GH_DENIED = re.compile(
    r"\bgh\b"
    + _SAME_COMMAND
    + "(?:"
    + "|".join(
        [
            *(_group_commands(g, c) for g, c in sorted(DENIED_COMMANDS.items())),
            *(
                _group_commands(g, frozenset({c})) + _SAME_COMMAND + _WORD + _words(a)
                for (g, c), a in sorted(DENIED_ACTIONS.items())
            ),
            _group("auth")
            + _SAME_COMMAND
            + _WORD
            + r"status\b"
            + _SAME_COMMAND
            + r"(?:--show-token\b|\s-a*ta*(?:\s|$))",
            _group(*DENIED_GROUPS),
            _WORD
            + r"pr\b"
            + _SAME_COMMAND
            + _WORD
            + r"merge\b"
            + _SAME_COMMAND
            + r"--admin\b",
            r"(?<!\w)rerun\b" + _SAME_COMMAND + FORK_REPOS.pattern,
            FORK_REPOS.pattern + _SAME_COMMAND + r"(?<!\w)rerun\b",
            RISKTHINKING + "/",
            "github\\.com/" + RISKTHINKING,
        ]
    )
    + ")"
    + r"|\bgh\s+[\"']?[$`]",
    re.IGNORECASE,
)
# Variables that set git's configuration or pick its files, past the -c and
# git config checks (MAR-343). GIT_CONFIG_NOSYSTEM only turns a file off.
_GIT_CONFIG_VARIABLE = re.compile(
    r"GIT_CONFIG(?:_(?:COUNT|PARAMETERS|GLOBAL|SYSTEM|KEY_[0-9]+|VALUE_[0-9]+))?"
)
# The same, for the git commands that make or push tags (MAR-289) or reach
# every branch, and those variables (MAR-343): git and its options, then the
# subcommand, so that a commit message saying "tag" doesn't count. Only for a
# command the hook can't parse, or when it fails.
_GIT_DENIED = re.compile(
    r"\bgit\b(?:\s+-[^\s;&|]+(?:\s+[^-\s;&|][^\s;&|]*)?)*?\s+[\"']?(?:"
    r"tag\b"
    r"|update-ref\b[^;&|\n]*(?:refs/tags|--stdin)"
    r"|submodule\b[^;&|\n]*foreach\b"
    r"|credential\b"
    r"|filter-branch\b"
    r"|rebase\b[^;&|\n]*(?:--ex|\s-[fikmnqv]*x)"
    r"|push\b[^;&|\n]*(?:--tags?\b|--follow-tags\b|--mirror\b|refs/tags"
    r"|--all\b|--branches\b|--prune\b"
    r"|\stag\s|[\s:+\"']v[^\s:]*"
    r"|[\s:+\"'](?:(?:refs/)?heads/)?(?:main|parametric)(?:[\s\"']|$))"
    r")"
    r"|\b" + _GIT_CONFIG_VARIABLE.pattern + "=",
    re.IGNORECASE,
)
_FORKISH = re.compile(
    r"forks|GH_REPO|GIT_DIR|GIT_WORK_TREE|\b(?:cd|pushd|popd|eval)\b|-C\b",
    re.IGNORECASE,
)


class ParseError(ValueError):
    """Shell syntax that the hook doesn't model, or an unterminated quote."""


class _Lexer:
    """Split shell text into simple commands, each a list of words.

    Quotes and escapes are removed from words. Commands inside ``$(...)``,
    backticks and ``<(...)`` are added to ``commands`` as commands of their
    own; the word that holds them keeps their raw text, so it contains ``$``
    or a backtick and counts as unresolvable. Redirection targets are dropped.
    """

    def __init__(self, text: str, depth: int) -> None:
        if depth > MAX_DEPTH:
            raise ParseError("commands nested too deeply")
        self.text = text
        self.depth = depth
        self.commands: list[list[str]] = []
        self.words: list[str] = []
        self.buf: list[str] = []
        self.has_word = False
        self.skip_word = False
        self.heredoc_strip: bool | None = None
        self.heredocs: list[tuple[str, bool]] = []

    def run(self, start: int = 0, nested: bool = False) -> int:
        """Lex from ``start``; return the index after the last character read.

        In nested mode, lexing stops after the ``)`` that closes the
        ``$(`` or ``<(`` whose content starts at ``start``.
        """
        text = self.text
        n = len(text)
        i = start
        parens = 0
        while i < n:
            c = text[i]
            if c == "\\":
                if text.startswith("\n", i + 1):
                    i += 2
                    continue
                self._add(text[i + 1 : i + 2])
                i += 2
            elif c == "'":
                end = text.find("'", i + 1)
                if end < 0:
                    raise ParseError("unterminated single quote")
                self._add(text[i + 1 : end])
                i = end + 1
            elif c == '"':
                i = self._double_quoted(i + 1)
            elif c == "$":
                i = self._dollar(i, quoted=False)
            elif c == "`":
                i = self._backticks(i)
            elif c == "#" and not self.has_word:
                end = text.find("\n", i)
                i = n if end < 0 else end
            elif c in " \t\r":
                self._end_word()
                i += 1
            elif c == "\n":
                self._end_command()
                i = self._skip_heredoc_bodies(i + 1)
            elif c in "<>" and text.startswith("(", i + 1):
                end = self._nested_commands(i + 2)
                self._add(text[i:end])
                i = end
            elif c == "(" and self._arithmetic_end(i) > 0:
                self._end_command()  # an arithmetic command, ((...))
                i = self._arithmetic(i)
            elif c == "(":
                self._end_command()
                parens += 1
                i += 1
            elif c == ")":
                self._end_command()
                i += 1
                if nested and parens == 0:
                    return i
                parens -= 1  # may go below 0 on a ``case`` pattern
            else:
                i = self._operator_or_char(i)
        if nested:
            raise ParseError("unterminated $( or <(")
        self._end_command()
        return n

    def _operator_or_char(self, i: int) -> int:
        text = self.text
        for op in _REDIRECTS:
            if text.startswith(op, i):
                if self.has_word and "".join(self.buf).isdigit():
                    self.buf = []  # a file descriptor, as in 2>&1
                    self.has_word = False
                self._end_word()
                if op in ("<<", "<<-"):
                    self.heredoc_strip = op == "<<-"
                else:
                    self.skip_word = True
                return i + len(op)
        for op in _SEPARATORS:
            if text.startswith(op, i):
                self._end_command()
                return i + len(op)
        self._add(text[i])
        return i + 1

    def _add(self, chars: str) -> None:
        self.buf.append(chars)
        self.has_word = True

    def _end_word(self) -> None:
        if not self.has_word:
            return
        word = "".join(self.buf)
        self.buf = []
        self.has_word = False
        if self.heredoc_strip is not None:
            self.heredocs.append((word, self.heredoc_strip))
            self.heredoc_strip = None
        elif self.skip_word:
            self.skip_word = False
        else:
            self.words.append(word)

    def _end_command(self) -> None:
        self._end_word()
        self.skip_word = False
        self.heredoc_strip = None
        if self.words:
            self.commands.append(self.words)
            self.words = []

    def _skip_heredoc_bodies(self, i: int) -> int:
        text = self.text
        n = len(text)
        while self.heredocs:
            delimiter, strip_tabs = self.heredocs.pop(0)
            while True:
                if i >= n:
                    return n  # an unterminated body runs to the end
                end = text.find("\n", i)
                end = n if end < 0 else end
                line = text[i:end]
                i = end + 1
                if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                    break
        return min(i, n)

    def _double_quoted(self, i: int) -> int:
        text = self.text
        n = len(text)
        self.has_word = True
        while i < n:
            c = text[i]
            if c == '"':
                return i + 1
            if c == "\\" and text[i + 1 : i + 2] in ("$", "`", '"', "\\", "\n"):
                if text[i + 1] != "\n":
                    self.buf.append(text[i + 1])
                i += 2
            elif c == "$":
                i = self._dollar(i, quoted=True)
            elif c == "`":
                i = self._backticks(i)
            else:
                self.buf.append(c)
                i += 1
        raise ParseError("unterminated double quote")

    def _arithmetic_end(self, i: int) -> int:
        """Return the index after the ``((...))`` at ``i``, or -1 if none.

        Its ``<<`` is a shift, not a here-document. ``((cmd) ...)``, whose
        last two parentheses aren't adjacent, is a subshell.
        """
        text = self.text
        if not text.startswith("((", i):
            return -1
        depth = 0
        for j in range(i, len(text)):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    return j + 1 if text[j - 1] == ")" else -1
        return -1

    def _arithmetic(self, i: int) -> int:
        """Skip the ``((...))`` at ``i``; lex its substitutions as commands."""
        end = self._arithmetic_end(i)
        inner = self.text[i + 2 : end - 2]
        if "$(" in inner or "`" in inner:
            sub = _Lexer(inner, self.depth + 1)
            sub.run()
            self.commands.extend(sub.commands)
        return end

    def _dollar(self, i: int, quoted: bool) -> int:
        text = self.text
        nxt = text[i + 1 : i + 2]
        if nxt == "(" and self._arithmetic_end(i + 1) > 0:
            end = self._arithmetic(i + 1)
            self._add(text[i:end])
            return end
        if nxt == "(":
            end = self._nested_commands(i + 2)
            self._add(text[i:end])
            return end
        if nxt == "{":
            end = self._parameter(i + 2)
            self._add(text[i:end])
            return end
        if nxt == "'" and not quoted:
            return self._ansi_c(i + 2)
        if nxt == '"' and not quoted:
            return i + 1  # $"..." is a translated string: lex the quotes
        self._add("$")
        return i + 1

    def _nested_commands(self, start: int) -> int:
        sub = _Lexer(self.text, self.depth + 1)
        end = sub.run(start, nested=True)
        self.commands.extend(sub.commands)
        return end

    def _parameter(self, i: int) -> int:
        text = self.text
        n = len(text)
        depth = 0
        while i < n:
            c = text[i]
            if c == "\\":
                i += 2
            elif c == "'":
                end = text.find("'", i + 1)
                if end < 0:
                    raise ParseError("unterminated single quote in ${...}")
                i = end + 1
            elif text.startswith("$(", i):
                i = self._nested_commands(i + 2)
            elif c == "{":
                depth += 1
                i += 1
            elif c == "}":
                if depth == 0:
                    return i + 1
                depth -= 1
                i += 1
            else:
                i += 1
        raise ParseError("unterminated ${")

    def _backticks(self, i: int) -> int:
        text = self.text
        n = len(text)
        j = i + 1
        while j < n and text[j] != "`":
            j += 2 if text[j] == "\\" else 1
        if j >= n:
            raise ParseError("unterminated backtick")
        inner = re.sub(r"\\([`$\\])", r"\1", text[i + 1 : j])
        sub = _Lexer(inner, self.depth + 1)
        sub.run()
        self.commands.extend(sub.commands)
        self._add(text[i : j + 1])
        return j + 1

    def _ansi_c(self, i: int) -> int:
        text = self.text
        n = len(text)
        self.has_word = True
        while i < n:
            c = text[i]
            if c == "'":
                return i + 1
            if c != "\\":
                self.buf.append(c)
                i += 1
                continue
            esc = text[i + 1 : i + 2]
            hexa = re.match(r"x([0-9A-Fa-f]{1,2})", text[i + 1 : i + 4])
            octal = re.match(r"[0-7]{1,3}", text[i + 1 : i + 4])
            if hexa:
                self.buf.append(chr(int(hexa.group(1), 16)))
                i += 1 + len(hexa.group(0))
            elif octal:
                self.buf.append(chr(int(octal.group(0), 8)))
                i += 1 + len(octal.group(0))
            else:
                self.buf.append(_ANSI_C.get(esc, "\\" + esc))
                i += 2
        raise ParseError("unterminated $'...'")


def split_commands(text: str, depth: int = 0) -> list[list[str]]:
    """Return every simple command in ``text``, nested ones included.

    Parameters
    ----------
    text
        Shell command text, as the Bash tool receives it.
    depth
        Nesting depth of ``text`` (for ``sh -c`` strings and ``eval``).

    Returns
    -------
    list of list of str
        The words of each simple command, with quotes and escapes removed.

    Raises
    ------
    ParseError
        On an unterminated quote or substitution, or nesting deeper than
        ``MAX_DEPTH``.
    """
    lexer = _Lexer(text, depth)
    lexer.run()
    commands: list[list[str]] = []
    for words in lexer.commands:
        commands.append(words)
        for script in _inner_scripts(words):
            commands.extend(split_commands(script, depth + 1))
    return commands


def _basename(word: str) -> str:
    if word.startswith("="):
        word = word[1:]  # zsh expands =gh to the path of gh
    return word.rsplit("/", 1)[-1]


def _inner_scripts(words: list[str]) -> list[str]:
    """Return the strings that ``sh -c``, ``bash -c`` or ``eval`` would run."""
    scripts = []
    for k, word in enumerate(words):
        if word == "eval":
            scripts.append(" ".join(words[k + 1 :]))
        elif _basename(word) in SHELLS:
            script = _shell_script(words[k + 1 :])
            if script is not None:
                scripts.append(script)
    return scripts


def _shell_script(args: list[str]) -> str | None:
    """Return the ``-c`` string of a shell's arguments, if it has one."""
    saw_c = False
    k = 0
    while k < len(args):
        arg = args[k]
        if arg in ("-o", "+o", "-O", "+O"):
            k += 2
            continue
        if arg != "--" and arg[:1] in ("-", "+") and len(arg) > 1:
            saw_c = saw_c or (not arg.startswith("--") and "c" in arg[1:])
        elif arg != "--":
            return arg if saw_c else None
        k += 1
    return None


def _git_locations(args: list[str]) -> list[tuple[str, str]]:
    """Return the ``-C``, ``--git-dir`` and ``--work-tree`` options of git.

    Each item is ``(option, value)``; only options before the subcommand count.
    """
    found = []
    k = 0
    while k < len(args):
        arg = args[k]
        if arg in ("-C", "--git-dir", "--work-tree"):
            found.append((arg, args[k + 1] if k + 1 < len(args) else ""))
            k += 2
            continue
        if arg in ("-c", "--namespace", "--config-env"):
            k += 2
            continue
        if arg.startswith(("--git-dir=", "--work-tree=")):
            option, value = arg.split("=", 1)
            found.append((option, value))
        elif arg.startswith("-C"):
            found.append(("-C", arg[2:]))
        elif not arg.startswith("-"):
            break  # the git subcommand
        k += 1
    return found


@dataclass
class GhInvocation:
    """A ``gh`` command found in the shell command.

    Attributes
    ----------
    words
        ``gh`` and its arguments.
    subcommand
        Its subcommand (the command group, e.g. ``pr``), by the group's own
        name if it is an alias in ``GROUP_ALIASES`` (``rs`` is ``ruleset``).
    repos
        The values of its ``--repo`` and ``-R`` flags, in order.
    placeholders
        For ``gh api``, the arguments in which gh fills in the repository.
    command
        The word after the subcommand that isn't a flag or a repo flag's
        value (e.g. ``create`` in ``gh release -R x create``), or ``""``.
    argument
        For ``gh repo view``, its repository argument, or ``""``.
    action
        For a command of ``DENIED_ACTIONS``, the first operand after it (e.g.
        ``add`` in ``gh repo deploy-key add``), or ``""``.
    rest
        The words after the command.
    """

    words: list[str]
    subcommand: str
    repos: list[str]
    placeholders: list[str] = field(default_factory=list)
    command: str = ""
    argument: str = ""
    action: str = ""
    rest: list[str] = field(default_factory=list)

    @property
    def checked(self) -> bool:
        """Whether it is checked in fork paths.

        The groups of ``CHECKED_SUBCOMMANDS`` are checked as a whole, the
        other groups' commands of ``REPO_FLAG_COMMANDS`` one by one, and
        ``gh repo view``.
        """
        if self.subcommand in CHECKED_SUBCOMMANDS:
            return True
        if self.command in REPO_FLAG_COMMANDS.get(self.subcommand, ()):
            return True
        return self.subcommand == "repo" and self.command == "view"

    @property
    def names_gh_command(self) -> bool:
        """Whether these words, after a variable, can only be a gh command.

        Other programs also have ``run`` and ``cache``, so those two need one
        of gh's own commands after them (MAR-343).
        """
        commands = AMBIGUOUS_GROUP_COMMANDS.get(self.subcommand)
        return self.checked if commands is None else self.command in commands

    @property
    def names_owner_repo(self) -> bool:
        """Whether it has a repo flag and every one names a marc272 repository."""
        return bool(self.repos) and all(
            _OWNER_REPO.fullmatch(repo) for repo in self.repos
        )

    @property
    def safe(self) -> bool:
        """Whether a fork path doesn't matter for it.

        An unchecked command is safe; ``gh api`` is safe without repository
        placeholders; ``gh repo view`` needs a ``marc272/`` repository as its
        argument; every other checked command needs ``names_owner_repo``.
        """
        if not self.checked:
            return True
        if self.subcommand == "api":
            return not self.placeholders
        if self.subcommand == "repo" and self.command == "view":
            return _OWNER_REPO.fullmatch(self.argument) is not None
        return self.names_owner_repo

    def denied(self) -> str | None:
        """Return why the deny rules refuse this command, or ``None``.

        Returns
        -------
        str or None
            ``"riskthinking"`` if an argument names a RiskThinking repository
            (any case; for ``gh api``, ``riskthinking`` anywhere);
            ``"expansion"`` if the subcommand, the command of a group in
            ``LITERAL_COMMAND_GROUPS``, the operand of a ``DENIED_ACTIONS``
            command, or a flag of ``gh pr merge`` is a word the shell expands;
            the subcommand for a group of ``DENIED_GROUPS``; ``"admin"`` for
            ``gh pr merge --admin``; ``"auth"`` for ``gh auth status`` showing
            the token; the subcommand for a command of ``DENIED_COMMANDS``;
            ``"config"``, or the command, for a ``DENIED_ACTIONS`` command;
            else ``None``.
        """
        args = [word.casefold() for word in self.words[1:]]
        marks = (RISKTHINKING + "/", "github.com/" + RISKTHINKING)
        if self.subcommand == "api":
            marks = (RISKTHINKING,)
        if any(mark in arg for arg in args for mark in marks):
            return "riskthinking"
        actions = DENIED_ACTIONS.get((self.subcommand, self.command), frozenset())
        if (
            _EXPANSION.search(self.subcommand)
            or (
                self.subcommand in LITERAL_COMMAND_GROUPS
                and _EXPANSION.search(self.command)
            )
            or (actions and _EXPANSION.search(self.action))
        ):
            return "expansion"
        if self.subcommand in DENIED_GROUPS:
            return self.subcommand
        if self.subcommand == "pr" and self.command == "merge":
            flags = args[: args.index("--")] if "--" in args else args
            if any(a == "--admin" or a.startswith("--admin=") for a in flags):
                return "admin"
            if _merge_flag_from_expansion(self.rest):
                return "expansion"
        if self.subcommand == "auth" and self.command == "status":
            if any(
                a == "--show-token"
                or a.startswith("--show-token=")
                or re.fullmatch(r"-a*ta*", a)
                for a in self.rest
            ):
                return "auth"
        if self.command in DENIED_COMMANDS.get(self.subcommand, ()):
            return self.subcommand
        if self.action in actions:
            return "config" if self.subcommand == "config" else self.command
        return None

    def writes_actions_permissions(self, fork_path: bool) -> bool:
        """Whether it changes a fork's Actions permissions (MAR-306, MAR-343).

        Actions stay off on ``marc272/crc-docs``: with them on, upstream's
        ``live`` job would reach RiskThinking's data. On ``marc272/crc-sdk``
        they are the merge gate. It is true for a ``gh api`` call that isn't a
        read and whose repository part, before ``actions/permissions``, names
        a fork, isn't literal, or has placeholders in a fork path.

        Parameters
        ----------
        fork_path
            Whether the command may run in a fork path.

        Returns
        -------
        bool
            Whether the write is denied.
        """
        if self.subcommand != "api" or not api_writes(self.words[1:]):
            return False
        for arg in self.words[1:]:
            match = _API_ACTIONS_PERMISSIONS.search(arg)
            if match is None:
                continue
            repo = arg[: match.start()]
            if (
                FORK_REPOS.search(repo)
                or _SHELL_VALUE.search(repo)
                or (fork_path and _API_PLACEHOLDER.search(repo))
            ):
                return True
        return False

    def reruns_fork_run(self, fork_path: bool) -> bool:
        """Whether it reruns a workflow run or job of a fork (MAR-282).

        ``gh run rerun`` does when a repo flag names ``crc-sdk`` or
        ``crc-docs`` or isn't literal, or when it has no repo flag and may run
        in a fork path. ``gh api`` does when the repository part of a rerun
        endpoint (``…/actions/runs/<id>/rerun…``, ``…/actions/jobs/<id>/rerun``)
        names a fork, isn't literal, or has placeholders in a fork path.

        Parameters
        ----------
        fork_path
            Whether the command may run in a fork path.

        Returns
        -------
        bool
            Whether the rerun is denied.
        """
        if self.subcommand == "run" and self.command == "rerun":
            if not self.repos:
                return fork_path
            return any(
                not repo or FORK_REPOS.search(repo) or _SHELL_VALUE.search(repo)
                for repo in self.repos
            )
        if self.subcommand != "api":
            return False
        for arg in self.words[1:]:
            rerun = _API_RERUN.search(arg)
            if rerun is None:
                continue
            repo = arg[: rerun.start()]
            if (
                FORK_REPOS.search(repo)
                or _SHELL_VALUE.search(repo)
                or (fork_path and _API_PLACEHOLDER.search(repo))
            ):
                return True
        return False


def _merge_flag_from_expansion(rest: list[str]) -> bool:
    """Whether ``gh pr merge`` may take a flag from an expansion (MAR-289).

    An expansion may be a value flag's value, or the first operand (the PR
    number: ``gh pr merge "$N" --squash``). Any other one could be ``--admin``
    (``gh pr merge 3 $X``), and so could a flag whose name is an expansion.

    Parameters
    ----------
    rest
        The words after ``gh pr merge``.

    Returns
    -------
    bool
        Whether a word that could be a flag comes from an expansion.
    """
    seen_operand = False
    k = 0
    while k < len(rest):
        arg = rest[k]
        if arg == "--":
            return False  # the rest are positional: none can be a flag
        if arg in PR_MERGE_VALUE_FLAGS:
            k += 2
            continue
        if arg.startswith("-") and arg != "-":
            if arg[:2] not in PR_MERGE_VALUE_FLAGS and _EXPANSION.search(
                arg.split("=", 1)[0]
            ):
                return True
        elif seen_operand and _EXPANSION.search(arg):
            return True
        else:
            seen_operand = True
        k += 1
    return False


def api_writes(args: list[str]) -> bool:
    """Whether ``gh api`` with these arguments sends anything but a GET.

    ``gh api`` uses ``-X``/``--method`` if given, else POST when a field or
    ``--input`` is given, else GET. A method that isn't literal counts as a
    write.

    Parameters
    ----------
    args
        The words after ``gh``.

    Returns
    -------
    bool
        Whether the call may write.
    """
    method = ""
    body = False
    k = 0
    while k < len(args):
        arg = args[k]
        if arg in ("-X", "--method"):
            method = args[k + 1] if k + 1 < len(args) else ""
            k += 2
            continue
        if arg.startswith("--method="):
            method = arg[len("--method=") :]
        elif arg.startswith("-X"):
            method = arg[2:].lstrip("=")
        elif (
            arg in _API_BODY_FLAGS
            or arg.split("=", 1)[0] in _API_BODY_FLAGS
            or arg[:2] in ("-f", "-F")
        ):
            body = True
        k += 1
    return method.upper() != "GET" if method else body


def api_placeholders(args: list[str]) -> list[str]:
    """Return the arguments of ``gh api`` in which gh fills in the repository.

    gh replaces ``{owner}``, ``{repo}``, ``:owner`` and ``:repo`` with the
    clone's repository in the endpoint and in ``-F``/``--field`` values. Every
    argument counts except the values of ``_API_LITERAL_FLAGS``, which gh
    never fills in, so an unknown flag or form errs towards refusing.

    Parameters
    ----------
    args
        The words after ``gh api``.

    Returns
    -------
    list of str
        The arguments that hold a placeholder, in order.
    """
    found = []
    k = 0
    while k < len(args):
        arg = args[k]
        if arg == "--":
            found += [a for a in args[k + 1 :] if _API_PLACEHOLDER.search(a)]
            break
        if arg in _API_LITERAL_FLAGS:
            k += 2  # the flag and its value
            continue
        if arg.startswith("--"):
            literal = "=" in arg and arg.split("=", 1)[0] in _API_LITERAL_FLAGS
        else:
            literal = len(arg) > 2 and arg[:2] in _API_LITERAL_FLAGS  # -qVALUE
        if not literal and _API_PLACEHOLDER.search(arg):
            found.append(arg)
        k += 1
    return found


def parse_gh(args: list[str]) -> GhInvocation | None:
    """Return the ``gh`` invocation that ``args`` make, if it has a subcommand.

    The repo flags (``-R X``, ``-RX``, ``-R=X``, ``--repo X``, ``--repo=X``)
    count wherever they stand before ``--``, as gh takes them before and
    after the subcommand. The subcommand is the first other word that isn't
    a flag, by its group's own name (``GROUP_ALIASES``), and the command the
    next one. For ``gh repo view``, the first word after the command that
    isn't a flag or a flag's value is its repository argument, and for a
    command of ``DENIED_ACTIONS`` its action.

    Parameters
    ----------
    args
        The words after ``gh``.

    Returns
    -------
    GhInvocation or None
        ``None`` if no word is a subcommand (e.g. ``gh --version``).
    """
    positional: list[tuple[int, str]] = []
    repos = []
    k = 0
    while k < len(args):
        arg = args[k]
        if arg == "--":
            break  # the rest are positional, not flags
        if arg in ("-R", "--repo"):
            repos.append(args[k + 1] if k + 1 < len(args) else "")
            k += 2
            continue
        if arg.startswith("--repo="):
            repos.append(arg[len("--repo=") :])
        elif arg.startswith("-R"):
            value = arg[2:]
            repos.append(value[1:] if value.startswith("=") else value)
        elif len(positional) < 2 and not arg.startswith("-"):
            positional.append((k, arg))
        k += 1
    if not positional:
        return None
    sub_at, subcommand = positional[0]
    subcommand = GROUP_ALIASES.get(subcommand, subcommand)
    placeholders = api_placeholders(args[sub_at + 1 :]) if subcommand == "api" else []
    command = positional[1][1] if len(positional) > 1 else ""
    rest = args[positional[1][0] + 1 :] if len(positional) > 1 else []
    argument = ""
    if subcommand == "repo" and command == "view":
        argument = _first_operand(rest, REPO_VIEW_VALUE_FLAGS)
    action = ""
    if (subcommand, command) in DENIED_ACTIONS:
        action = _first_operand(rest, ACTION_VALUE_FLAGS)
    return GhInvocation(
        words=["gh", *args],
        subcommand=subcommand,
        repos=repos,
        placeholders=placeholders,
        command=command,
        argument=argument,
        action=action,
        rest=rest,
    )


@dataclass
class GitInvocation:
    """A ``git`` command found in the shell command (MAR-289).

    Attributes
    ----------
    words
        ``git`` and its arguments.
    subcommand
        Its subcommand (e.g. ``push``).
    args
        The words after the subcommand.
    config
        The keys that ``-c`` and ``--config-env`` set for this command.
    from_stdin
        Whether ``xargs`` or ``parallel`` runs it, and so may add operands
        that the hook can't see.
    from_environment
        Whether ``words`` set git's configuration through the environment
        (MAR-343), rather than being a git command.
    """

    words: list[str]
    subcommand: str
    args: list[str]
    config: list[str]
    from_stdin: bool = False
    from_environment: bool = False

    def denied(self) -> str | None:
        """Return why the hook refuses this command, or ``None``.

        Returns
        -------
        str or None
            ``"git-expansion"`` if the subcommand, a configuration key, the
            ref of ``git update-ref``, an operand or flag name of ``git
            push``, or a flag name of ``git rebase`` is a word the shell
            expands, or ``xargs`` or ``parallel`` supplies operands to ``git
            push`` or ``update-ref``; ``"git-config"`` for
            configuration that adds a
            command or carries tags; ``"git-tag"`` for a command that makes a
            tag; ``"git-push"`` for one that pushes tags or everything;
            ``"git-push-all"`` for one that reaches every branch,
            ``"git-push-shared"`` for one whose destination is a shared branch
            (MAR-355), ``"git-environment"`` for configuration set through the
            environment and ``"git-submodule"`` for ``git submodule foreach``
            (MAR-343), ``"git-credential"`` for ``git credential`` and its
            helpers and ``"git-exec"`` for ``git rebase --exec`` and ``git
            filter-branch`` (MAR-355); else ``None``. Local tags alone do
            nothing, so other plumbing that writes a ref isn't checked: a tag
            has to be pushed.
        """
        if self.from_environment:
            return "git-environment"
        for key in self.config:
            if _EXPANSION.search(key):
                return "git-expansion"
            if GIT_TAG_CONFIG.fullmatch(key.casefold()):
                return "git-config"
        if _EXPANSION.search(self.subcommand):
            return "git-expansion"
        if self.from_stdin and self.subcommand in ("push", "update-ref"):
            return "git-expansion"
        if self.subcommand == "tag":
            return "git-tag"
        if self.subcommand == "update-ref":
            return _update_ref_problem(self.args)
        if self.subcommand == "push":
            return _push_problem(self.args)
        if self.subcommand in GIT_PUSH_PLUMBING:
            return "git-push"
        if self.subcommand == "config":
            return _config_problem(self.args)
        if self.subcommand == "submodule":
            return _submodule_problem(self.args)
        if self.subcommand == "credential" or self.subcommand.startswith("credential-"):
            return "git-credential"
        if self.subcommand == "filter-branch":
            return "git-exec"
        if self.subcommand == "rebase":
            return _rebase_problem(self.args)
        if self.subcommand == "remote" and self.args[:1] == ["add"]:
            mirror = any(arg.startswith("--mirror") for arg in self.args)
            return "git-push" if mirror else None
        return None


def _update_ref_problem(args: list[str]) -> str | None:
    """Return why ``git update-ref`` with these arguments is refused, if it is."""
    if "--stdin" in args or any("refs/tags" in arg.casefold() for arg in args):
        return "git-tag"
    if _EXPANSION.search(_first_operand(args, frozenset({"-m"}))):
        return "git-expansion"
    return None


def _push_problem(args: list[str]) -> str | None:
    """Return why ``git push`` with these arguments is refused, if it is.

    Parameters
    ----------
    args
        The words after ``git push``.

    Returns
    -------
    str or None
        ``"git-push"`` for a flag that sends tags (abbreviated too) or a
        refspec that names one, ``"git-push-all"`` for a flag that reaches
        every branch or the matching refspec (``:`` or ``+:``),
        ``"git-push-shared"`` for a refspec whose destination is ``main`` or
        ``parametric``, ``"git-expansion"`` for an operand or a flag name the
        shell expands, as the hook can't tell what it would push, else
        ``None``.
    """
    operands: list[str] = []
    k = 0
    while k < len(args):
        arg = args[k]
        if arg == "--":
            operands += args[k + 1 :]
            break
        if arg in GIT_PUSH_VALUE_FLAGS:
            k += 2
            continue
        if arg.startswith("--"):
            name = arg.split("=", 1)[0]
            if _EXPANSION.search(name):
                return "git-expansion"  # --$X could be any of these flags
            if _abbreviates(name, GIT_PUSH_TAG_FLAGS):
                return "git-push"
            if _abbreviates(name, GIT_PUSH_EVERY_BRANCH_FLAGS):
                return "git-push-all"
        elif not arg.startswith("-"):
            operands.append(arg)
        k += 1
    if any(_EXPANSION.search(operand) for operand in operands):
        return "git-expansion"
    refspecs = operands[1:]  # the first operand is the remote
    if any(refspec.lstrip("+") == ":" for refspec in refspecs):
        return "git-push-all"  # the matching refspec: every branch both sides have
    if any(map(_names_shared_branch, refspecs)):
        return "git-push-shared"
    return "git-push" if any(map(_names_tag, refspecs)) else None


def _abbreviates(name: str, flags: tuple[tuple[str, int], ...]) -> bool:
    """Whether a long flag is one of ``flags``, abbreviated as git allows."""
    return any(
        len(name) >= shortest and flag.startswith(name) for flag, shortest in flags
    )


def _names_tag(refspec: str) -> bool:
    """Whether a refspec of ``git push`` may name a tag.

    A bare word can be a branch or a tag, and only the name tells. It counts
    if it could trigger crc-sdk's Package release, which runs on ``v*`` tags.
    """
    if refspec == "tag" or "refs/tags" in refspec.casefold():
        return True
    return any(
        side.startswith("v") or side.casefold().startswith("tags/")
        for side in refspec.lstrip("+").split(":")
    )


def _names_shared_branch(refspec: str) -> bool:
    """Whether a refspec of ``git push`` writes ``main`` or ``parametric``.

    Only the destination counts (MAR-355): what follows the last colon, or the
    source when that is empty or there is no colon. So ``git push origin
    main:marcprinzing/x`` passes. ``HEAD`` names no branch: the hook reads the
    command, not the checkout, so it can't tell what a push of ``HEAD`` writes.

    Parameters
    ----------
    refspec
        One refspec of ``git push``, with or without a leading ``+``.

    Returns
    -------
    bool
        Whether the destination is a shared branch.
    """
    source, _, destination = refspec.lstrip("+").rpartition(":")
    return _SHARED_BRANCH.fullmatch(destination or source) is not None


def _config_problem(args: list[str]) -> str | None:
    """Return why ``git config`` with these arguments is refused, if it is."""
    if args[:1] and args[0] in GIT_CONFIG_READ_VERBS:
        return None
    if any(arg in GIT_CONFIG_READ_FLAGS for arg in args):
        return None
    return (
        "git-config"
        if any(GIT_TAG_CONFIG.fullmatch(arg.casefold()) for arg in args)
        else None
    )


def _submodule_problem(args: list[str]) -> str | None:
    """Return why ``git submodule`` with these arguments is refused, if it is.

    ``foreach`` runs a shell string in each submodule, which the hook doesn't
    read. A command from an expansion could be ``foreach``.
    """
    command = _first_operand(args, frozenset())
    if command == "foreach":
        return "git-submodule"
    return "git-expansion" if _EXPANSION.search(command) else None


def _rebase_problem(args: list[str]) -> str | None:
    """Return why ``git rebase`` with these arguments is refused, if it is.

    ``--exec`` and ``-x`` run a shell string after each commit, which the hook
    doesn't read. A flag name from an expansion could be either of them; a
    commit from an expansion (``git rebase "$BASE"``) passes.

    Parameters
    ----------
    args
        The words after ``git rebase``.

    Returns
    -------
    str or None
        ``"git-exec"`` for the flag, in any spelling git accepts,
        ``"git-expansion"`` for a flag name the shell expands, else ``None``.
    """
    for arg in args:
        if arg == "--":
            return None  # the rest are operands
        if not arg.startswith("-"):
            continue
        name = arg.split("=", 1)[0]
        if _EXPANSION.search(name):
            return "git-expansion"
        if _abbreviates(name, GIT_REBASE_EXEC_FLAGS) or _REBASE_SHORT_EXEC.match(arg):
            return "git-exec"
    return None


def _git_config_assignment(words: list[str]) -> str | None:
    """Return the word that sets git's configuration in the environment, if any.

    A word counts when it assigns a variable of ``_GIT_CONFIG_VARIABLE`` and
    stands where the shell or ``env`` takes it as one: among a command's
    leading assignments, or after ``env``, ``export`` and the like. So
    ``grep GIT_CONFIG_COUNT=1 notes.md`` doesn't count.

    Parameters
    ----------
    words
        The words of one simple command.

    Returns
    -------
    str or None
        The assignment, or ``None``.
    """
    for k, word in enumerate(words):
        assignment = _ASSIGNMENT.fullmatch(word)
        if assignment is None:
            continue
        if not _GIT_CONFIG_VARIABLE.fullmatch(assignment.group(1)):
            continue
        before = words[:k]
        if all(w in _KEYWORDS or _ASSIGNMENT.fullmatch(w) for w in before) or any(
            _basename(w) in _ENVIRONMENT_SETTERS for w in before
        ):
            return word
    return None


def _at_program_position(words: list[str], k: int) -> bool:
    """Whether ``words[k]`` stands where a program does (MAR-343).

    Only keywords, assignments, wrappers, their flags and a duration may come
    before it, so that ``grep "$X" pr list`` doesn't count, and it isn't an
    assignment itself (``X="$Y" pr list`` runs ``pr``).

    Parameters
    ----------
    words
        The words of one simple command.
    k
        The index of the word.

    Returns
    -------
    bool
        Whether the word is in the program's position.
    """
    if _ASSIGNMENT.fullmatch(words[k]):
        return False
    return all(
        word in _KEYWORDS
        or word in _PRECOMMANDS
        or _ASSIGNMENT.fullmatch(word)
        or _basename(word) in _WRAPPERS
        or word.startswith("-")
        or _DURATION.fullmatch(word)
        for word in words[:k]
    )


def parse_git(args: list[str]) -> GitInvocation | None:
    """Return the ``git`` invocation that ``args`` make, if it has a subcommand.

    Parameters
    ----------
    args
        The words after ``git``.

    Returns
    -------
    GitInvocation or None
        ``None`` if no word is a subcommand (e.g. ``git --version``).
    """
    config: list[str] = []
    k = 0
    while k < len(args):
        arg = args[k]
        if arg in GIT_VALUE_OPTIONS:
            k += 2
            continue
        if arg in ("-c", "--config-env"):
            value = args[k + 1] if k + 1 < len(args) else ""
            config.append(value.split("=", 1)[0])
            k += 2
            continue
        if arg.startswith("--config-env="):
            config.append(arg[len("--config-env=") :].split("=", 1)[0])
        elif not arg.startswith("-"):
            return GitInvocation(["git", *args], arg, args[k + 1 :], config)
        k += 1
    return None


def _first_operand(args: list[str], value_flags: frozenset[str]) -> str:
    """Return the first word of ``args`` that isn't a flag or a flag's value."""
    k = 0
    while k < len(args):
        arg = args[k]
        if arg == "--":
            return args[k + 1] if k + 1 < len(args) else ""
        if arg in value_flags or arg in ("-R", "--repo"):
            k += 2
            continue
        if not arg.startswith("-"):
            return arg
        k += 1
    return ""


def _norm_root(path: str) -> str:
    return os.path.normpath(path).casefold()


_ROOTS = tuple(
    sorted({_norm_root(FORKS_ROOT), _norm_root(os.path.realpath(FORKS_ROOT))})
)


def under_forks(path: str) -> bool:
    """Whether an absolute ``path`` is ``FORKS_ROOT`` or below it.

    The path is compared as written and with symlinks resolved, ignoring case.

    Parameters
    ----------
    path
        An absolute path.

    Returns
    -------
    bool
        ``True`` if the path is under the forks root.
    """
    try:
        real = os.path.realpath(path)
    except (OSError, ValueError):
        real = path  # can't resolve symlinks: check the path as written
    candidates = {os.path.normpath(path).casefold(), real.casefold()}
    return any(
        c == root or c.startswith(root.rstrip("/") + "/")
        for c in candidates
        for root in _ROOTS
    )


@dataclass
class _Context:
    """What the hook learns about one shell command.

    ``starts`` are the directories the command may start in: one for Bash
    and Monitor, one or more for the terminal tool (``terminal_starts``).
    """

    starts: list[str]
    home: str
    cwds: list[str] = field(default_factory=list)
    unknown_cwd: bool = False
    reasons: list[str] = field(default_factory=list)
    fork_paths: list[str] = field(default_factory=list)
    invocations: list[GhInvocation] = field(default_factory=list)
    git_invocations: list[GitInvocation] = field(default_factory=list)

    def __post_init__(self) -> None:
        for start in self.starts:
            path = os.path.normpath(start)
            if path not in self.cwds:
                self.cwds.append(path)
            if under_forks(path):
                self._fork(f"the command starts in {path}", path)

    def _fork(self, reason: str, path: str | None = None) -> None:
        if path is not None:
            if path in self.fork_paths:
                return  # one reason per path is enough
            self.fork_paths.append(path)
        if reason not in self.reasons:
            self.reasons.append(reason)

    def expand(self, word: str) -> str:
        """Expand ``~``, ``$HOME`` and ``${HOME}`` in ``word``."""
        if word == "~" or word.startswith("~/"):
            word = self.home + word[1:]
        elif word.startswith("~"):
            word = os.path.expanduser(word)
        return _HOME_VARIABLE.sub(lambda _: self.home, word)

    def resolve(self, word: str, cwds: list[str] | None = None) -> list[str] | None:
        """Return the absolute paths ``word`` may name, or ``None`` if unknown.

        A relative path is resolved against every possible working directory,
        or against ``cwds`` if given.
        """
        path = self.expand(word)
        if not path or _UNRESOLVABLE.search(path):
            return None
        if os.path.isabs(path):
            return [os.path.normpath(path)]
        if self.unknown_cwd:
            return None
        bases = self.cwds if cwds is None else cwds
        return [os.path.normpath(os.path.join(c, path)) for c in bases]

    def change_directory(self, words: list[str]) -> None:
        """Follow a ``cd``, ``pushd`` or ``popd`` that ``words`` runs."""
        k = 0
        while k < len(words) and (
            words[k] in _KEYWORDS or _ASSIGNMENT.fullmatch(words[k])
        ):
            k += 1
        while k < len(words) and words[k] in _PRECOMMANDS:
            k += 1
        if k >= len(words):
            return
        name, args = words[k], words[k + 1 :]
        if name not in ("cd", "pushd", "popd", "chdir"):
            if not args and _BARE_CD.fullmatch(name):
                self._unresolved_cd(name)  # zsh: "-" or "2" may be cd aliases
            return
        operands = [a for a in args if a == "-" or not a.startswith("-")]
        operands += [a for a in args if re.fullmatch(r"-[0-9]+", a)]
        shown = " ".join(words[k:])
        if name == "popd" or (name == "pushd" and not operands):
            self._unresolved_cd(shown)
            return
        target = operands[0] if operands else self.home
        if len(operands) > 1 or _DIR_STACK.fullmatch(target):
            self._unresolved_cd(shown)
            return
        paths = self.resolve(target)
        if paths is None:
            self._unresolved_cd(shown)
            return
        for path in paths:
            if under_forks(path):
                self._fork(f"`{shown}` goes to {path}", path)
            if path not in self.cwds:
                self.cwds.append(path)
        if len(self.cwds) > MAX_CWDS:
            self.unknown_cwd = True
            self._fork("too many directory changes to follow")

    def _unresolved_cd(self, shown: str) -> None:
        self.unknown_cwd = True
        self._fork(f"`{shown}` changes to a directory the hook can't resolve")

    def location(self, shown: str, value: str) -> None:
        """Check a git location option or variable, shown as ``shown``."""
        paths = self.resolve(value)
        if paths is None:
            self._fork(f"`{shown}` points to a path the hook can't resolve")
            return
        for path in paths:
            if under_forks(path):
                self._fork(f"`{shown}` points to {path}", path)

    def mention(self, word: str) -> None:
        """Check whether a word of the command names a path under the forks."""
        candidates = [word]
        if "=" in word:
            candidates.append(word.split("=", 1)[1])
        # A working directory under the forks has already given its reason.
        outside = [c for c in self.cwds if not under_forks(c)]
        for candidate in candidates:
            expanded = self.expand(candidate)
            folded = expanded.casefold()
            if any(root in folded for root in _ROOTS):
                self._fork(f"the command names {candidate}", expanded)
                return
            if _UNRESOLVABLE.search(expanded) or not expanded:
                continue
            for path in self.resolve(expanded, outside) or []:
                if under_forks(path):
                    self._fork(f"the command names {candidate} ({path})", path)
                    return

    def inspect(self, words: list[str]) -> None:
        """Record the fork signals and the gh invocation of one command."""
        if _git_config_assignment(words) is not None:
            self.git_invocations.append(
                GitInvocation(words, "", [], [], from_environment=True)
            )
        gh_at = next(
            (k for k, w in enumerate(words) if _basename(w) == "gh"), len(words)
        )
        before = words[:gh_at]
        for k, word in enumerate(before):
            if _basename(word) == "git":
                for option, value in _git_locations(before[k + 1 :]):
                    self.location(f"git {option} {value}", value)
            assignment = _ASSIGNMENT.fullmatch(word)
            if assignment and assignment.group(1) in LOCATION_VARIABLES:
                self.location(word, assignment.group(2))
            elif assignment and assignment.group(1) == "GH_REPO":
                self._fork(f"`{word}` sets GH_REPO; only --repo or -R counts")
            self.mention(word)
        if gh_at < len(words):
            invocation = parse_gh(words[gh_at + 1 :])
            if invocation is not None:
                self.invocations.append(invocation)
        git_at = next(
            (k for k, w in enumerate(words) if _basename(w) == "git"), len(words)
        )
        if git_at < gh_at:  # a git word after gh is one of gh's arguments
            git = parse_git(words[git_at + 1 :])
            if git is not None:
                git.from_stdin = any(
                    _basename(word) in ARGUMENT_FEEDERS for word in words[:git_at]
                )
                self.git_invocations.append(git)
        if gh_at == len(words) and git_at == len(words):
            self._program_from_expansion(words)

    def _program_from_expansion(self, words: list[str]) -> None:
        """Record a gh or git command run from a variable (MAR-289, MAR-343).

        Neither ``gh`` nor ``git`` is a word of ``words``. If the words after
        an expansion would be a denied command (``$GH release create v1``),
        the expansion counts as the program. It also counts when it stands
        where a program does and the words after it can only be gh's
        (``GhInvocation.names_gh_command``), so that the fork-path check runs
        on ``$GH pr list``. Other commands from a variable (``$PY -m pytest``,
        ``$UV run pytest``) pass.
        """
        for k, word in enumerate(words):
            if not _SHELL_VALUE.search(word):
                continue
            gh = parse_gh(words[k + 1 :])
            if (
                gh is not None
                and gh.subcommand in GH_GROUPS
                and gh.denied() not in (None, "expansion")
            ):
                gh.words[0] = word
                self.invocations.append(gh)
                return
            git = parse_git(words[k + 1 :])
            if git is not None and git.denied() not in (None, "git-expansion"):
                git.words[0] = word
                self.git_invocations.append(git)
                return
            if (
                gh is not None
                and gh.denied() is None
                and gh.names_gh_command
                and _at_program_position(words, k)
            ):
                gh.words[0] = word
                self.invocations.append(gh)
                return


def evaluate(command: str, starts: list[str], home: str) -> str | None:
    """Return the refusal message for a shell command, or ``None`` to allow it.

    Parameters
    ----------
    command
        The tool's ``command``.
    starts
        The directories the command may start in (the hook input's ``cwd``,
        or ``terminal_starts`` for the terminal tool).
    home
        The home directory, for ``~`` and ``$HOME``.

    Returns
    -------
    str or None
        Why the command is refused and how to fix it, or ``None``. A denied
        gh or git command (``GhInvocation.denied``, ``GitInvocation.denied``)
        is refused wherever it runs, then a rerun of a fork's run
        (``GhInvocation.reruns_fork_run``) and a write to crc-docs' Actions
        permissions (``GhInvocation.writes_actions_permissions``), all before
        the fork-path check.

    Raises
    ------
    ParseError
        If the command can't be split into simple commands.
    """
    commands = split_commands(command)
    context = _Context(starts=starts, home=home)
    for words in commands:
        context.change_directory(words)
    for words in commands:
        context.inspect(words)
    for invocation in [*context.invocations, *context.git_invocations]:
        kind = invocation.denied()
        if kind is not None:
            return _denial(invocation, kind)
    for invocation in context.invocations:
        if invocation.reruns_fork_run(bool(context.reasons)):
            return _denial(invocation, "rerun")
        if invocation.writes_actions_permissions(bool(context.reasons)):
            return _denial(invocation, "actions-permissions")
    unsafe = [i for i in context.invocations if not i.safe]
    if not unsafe or not context.reasons:
        return None
    return _refusal(unsafe[0], context)


def _guess_fork(paths: list[str]) -> str:
    """Return the fork a path under the forks root belongs to, if it shows."""
    for path in paths:
        folded = path.casefold()
        for root in _ROOTS:
            at = folded.find(root)
            if at < 0:
                continue
            rest = folded[at + len(root) :].strip("/").split("/")
            for part in rest[:2]:  # <fork>/... or worktrees/<fork>-mar-<n>
                for fork in ("crc-sdk", "crc-docs"):
                    if part.startswith(fork):
                        return fork
    return "<fork>"


def _refusal(invocation: GhInvocation, context: _Context) -> str:
    shown = " ".join(invocation.words)
    if len(shown) > 160:
        shown = shown[:157] + "..."
    fork = _guess_fork(context.fork_paths)
    lines = [
        "Refused by the fork gh guard (.claude/hooks/fork_gh_guard.py, MAR-253):",
        f"  {shown}",
    ]
    repo_view = invocation.subcommand == "repo" and invocation.command == "view"
    if invocation.subcommand == "api":
        values = ", ".join(repr(word) for word in invocation.placeholders[:3])
        lines += [
            "may run in a CRC fork, and gh api fills in {owner}/{repo} (or",
            f":owner/:repo) from the clone's repository, in {values}.",
        ]
    elif repo_view:
        lines.append(
            "may run in a CRC fork, and it doesn't name a literal"
            f" {OWNER}/<repo> as its argument."
        )
    else:
        lines.append(
            f"may run in a CRC fork, and it doesn't pass --repo {OWNER}/<fork>"
            f" (or -R {OWNER}/<fork>)."
        )
        bad = [repo for repo in invocation.repos if not _OWNER_REPO.fullmatch(repo)]
        if bad:
            values = ", ".join(repr(repo) for repo in bad)
            lines.append(
                f"Its --repo/-R value {values} is not a literal {OWNER}/<repo>"
                " (no variables)."
            )
    lines.append("Why the hook counts it as a fork path:")
    lines += [f"  - {reason}" for reason in context.reasons[:3]]
    lines += [
        "In a fork clone, gh can take the clone's repository to be the parent,",
        "RiskThinking's, where agents must never act.",
    ]
    if invocation.subcommand == "api":
        lines += [
            "Fix: gh api has no --repo, so write the repository out:",
            f"  gh api repos/{OWNER}/{fork}/pulls ...",
            f"  gh api graphql -F owner={OWNER} -F name={fork} -f query=...",
        ]
    elif invocation.subcommand in ("pr", "issue"):
        lines += [
            "Fix: name the fork explicitly, as docs/ORCHESTRATION.md does:",
            f"  gh pr create --repo {OWNER}/{fork} --base parametric"
            " --head <branch> ...",
            f"  gh pr checks <n> --repo {OWNER}/{fork}",
            f"  gh pr merge <n> --repo {OWNER}/{fork} --squash ...",
        ]
    elif repo_view:
        lines += [
            "Fix: name the fork explicitly:",
            f"  gh repo view {OWNER}/{fork} ...",
        ]
    else:
        command = invocation.command
        if invocation.subcommand not in REPO_FLAG_COMMANDS:
            command = "<command>"
        lines += [
            "Fix: name the fork explicitly:",
            f"  gh {invocation.subcommand} {command} ... --repo {OWNER}/{fork}",
        ]
    lines.append(
        "For this repository's own PRs, issues and runs, pass --repo"
        f" {OWNER}/parametric-insurance-design."
    )
    return "\n".join(lines)


# What each kind of denied gh command (GhInvocation.denied) covers, and why
# it is Marc's.
_DENIALS = {
    "release": (
        "gh release create (or new), edit, upload, delete and delete-asset.",
        "Releases and tags are Marc's: in crc-sdk, a v* tag or a manual run of",
        "release.yaml publishes a release.",
    ),
    "workflow": (
        "gh workflow run, enable and disable. CI runs on push and pull request,",
        "and manual runs are Marc's: in crc-sdk, a manual run of release.yaml",
        "publishes a release.",
    ),
    "repo": (
        "gh repo create (or new), delete, edit, fork, sync, archive, unarchive",
        "and rename. Repositories are Marc's.",
    ),
    "admin": (
        "gh pr merge --admin. Nobody merges past branch protection: the",
        "orchestrator merges with gh pr merge <n> --squash (runbook, Merge policy).",
    ),
    "riskthinking": (
        "any gh command that names a RiskThinking repository. Agents never act",
        "on RiskThinking's repositories and read upstream only through",
        "git fetch upstream. A PR body or comment that mentions one goes in a",
        "file, passed with --body-file.",
    ),
    "alias": (
        "gh alias set and import. An alias is a new gh command, which the deny",
        "rules and this hook can't see through.",
    ),
    "extension": (
        "gh extension install (also gh ext and gh extensions). An extension is",
        "third-party code that runs as a new gh command, past the deny rules.",
    ),
    "skill": (
        "gh skill install (or add), update and publish (also gh skills).",
        "Install and update write agent skills, instructions and commands from",
        "another repository; publish creates a tag and a GitHub release, and",
        "tags and releases are Marc's.",
    ),
    "copilot": (
        "gh copilot. It downloads and runs the GitHub Copilot CLI, another agent,",
        "outside this project's deny rules and hooks.",
    ),
    "rerun": (
        "gh run rerun of a run in a fork, crc-sdk or crc-docs (with its --repo,",
        "or in a fork path), and the gh api rerun endpoints there. A rerun is a",
        "manual run, and manual runs in the forks are Marc's: rerunning a",
        "crc-sdk Package release run publishes again. To rerun a PR's CI, push",
        "a commit to its branch.",
    ),
    "expansion": (
        "a gh command whose subcommand is a word the shell expands ($var, $(...),",
        "backticks, a glob or braces), or whose command is one, for gh release,",
        "workflow, repo, pr, run, alias, extension, skill, project, agent-task,",
        "gist, auth and config (gh release cre{ate,} runs gh release create);",
        "and an expansion among gh pr merge's flags (gh pr merge 3 $X), which",
        "could be --admin. Neither the deny rules nor this hook can tell which",
        "command it runs. A PR number or a --subject or --body value is fine.",
    ),
    "deploy-key": (
        "gh repo deploy-key add and delete. A write deploy key is a new push",
        "credential, and deploy keys are repository settings, which are Marc's.",
    ),
    "autolink": (
        "gh repo autolink create (or new) and delete. Autolinks are repository",
        "settings, which are Marc's.",
    ),
    "gist": (
        "gh gist create (or new), edit, rename and delete. A gist publishes",
        "outside the program's repositories, which AGENTS.md forbids, and an",
        "existing gist is Marc's.",
    ),
    "agent-task": (
        "gh agent-task create (also gh agent, agents, agent-tasks). It starts a",
        "Copilot coding agent that pushes branches and opens PRs on the repository.",
    ),
    "config": (
        "gh config set editor, pager and browser. Each names a program that gh",
        "runs later, outside the deny rules and this hook.",
    ),
    "auth": (
        "gh auth login, logout, refresh, switch, setup-git and git-credential,",
        "gh auth token and gh auth status --show-token (-t). They sign in, change",
        "which account or credential gh and git use, or print a credential, and",
        "agents never sign in, use or store credentials (AGENTS.md).",
    ),
    "actions-permissions": (
        "a gh api write to actions/permissions of marc272/crc-docs or",
        "marc272/crc-sdk (reading it is fine). Actions stay off on crc-docs: with",
        "them on, upstream's live job would reach RiskThinking's data (runbook,",
        "Fork PRs). On crc-sdk they are the merge gate. Changing either is Marc's.",
    ),
    "git-tag": (
        "git tag, and git update-ref on refs/tags or with --stdin. Tags are",
        "Marc's: in crc-sdk, a pushed v* tag runs the Package release. To read",
        "tags, use git for-each-ref refs/tags or git ls-remote --tags origin.",
    ),
    "git-push": (
        "a git push that sends tags or every ref: --tags, --follow-tags, --mirror",
        "(abbreviated too), the word tag, a refspec with refs/tags or tags/, a",
        "refspec whose source or destination starts with v, to any remote, in",
        "quotes or not; a remote added with --mirror; and git send-pack and",
        "http-push. In crc-sdk, a pushed v* tag runs the Package release.",
    ),
    "git-push-all": (
        "git push --all, its alias --branches and --prune (abbreviated too), and",
        "the matching refspec (: or +:). --all, --branches and : push every local",
        "branch, a local main and parametric included; --prune deletes the",
        "remote's branches that have no local counterpart.",
    ),
    "git-push-shared": (
        "a git push whose destination is main or parametric, in any spelling: the",
        "bare name, heads/<name>, refs/heads/<name>, <src>:<name> or <name>:, to",
        "any remote, a force or a delete included. Those branches change only",
        "through merged PRs (AGENTS.md).",
    ),
    "git-environment": (
        "a variable that sets git's configuration or picks its files:",
        "GIT_CONFIG_COUNT, GIT_CONFIG_KEY_<n>, GIT_CONFIG_VALUE_<n>,",
        "GIT_CONFIG_PARAMETERS, GIT_CONFIG_GLOBAL, GIT_CONFIG_SYSTEM and",
        "GIT_CONFIG. They can make a plain git push carry tags, or add a git",
        "command, past the git -c and git config checks.",
    ),
    "git-submodule": (
        "git submodule foreach. It runs a shell string in each submodule, which",
        "neither the deny rules nor this hook read.",
    ),
    "git-credential": (
        "git credential and the git credential-<helper> commands. git credential",
        "fill can print the token that gh auth token would, and approve and",
        "reject change what is stored; agents never use or store credentials",
        "(AGENTS.md).",
    ),
    "git-exec": (
        "git rebase --exec (-x, abbreviated or in a cluster such as -ix too) and",
        "git filter-branch. Each runs a shell string that neither the deny rules",
        "nor this hook read. git rebase without them passes.",
    ),
    "git-config": (
        "git config and git -c on push.followTags, push.default,",
        "remote.<name>.push, remote.<name>.mirror and alias.<name>. Each makes a",
        "plain git push carry tags or every matching branch, or adds a git",
        "command that the deny rules and this hook can't see through.",
    ),
    "git-expansion": (
        "a git command whose subcommand, configuration key, git update-ref ref,",
        "git push operand or flag name, or git rebase flag name is a word the",
        "shell expands ($var, $(...), backticks, a glob or braces), and git push",
        "or update-ref run by xargs or parallel.",
        "Neither the deny rules nor this hook can tell what it would do, or which",
        "refs it would push.",
    ),
}
_DENIED_MARK = "is denied in every spelling"
_CHECKED_LIST = ", ".join(sorted(REPO_FLAG_SUBCOMMANDS)) + " or api"


def _denial(invocation: GhInvocation | GitInvocation, kind: str) -> str:
    shown = " ".join(invocation.words)
    if len(shown) > 160:
        shown = shown[:157] + "..."
    footer = [
        "The deny rules in .claude/settings.json match the command text; this",
        "hook also refuses the other spellings (-R/--repo before or after the",
        "group, gh by path, sh -c). Leave it to Marc (docs/ORCHESTRATION.md,",
        '"One-time setup", step 4).',
    ]
    if kind == "expansion":
        footer = [
            "Fix: write the gh subcommand and command out as plain words, one gh",
            "command per call if a loop needs several.",
        ]
    elif kind == "git-expansion":
        footer = [
            "Fix: write the branch and the git subcommand out as plain words:",
            "  git -C <worktree> push -u origin <branch>",
        ]
    elif kind.startswith("git-"):
        footer = [
            "The deny rules in .claude/settings.json match the command text; this",
            "hook also refuses the other spellings (git by path, -c, quotes, a URL",
            'as the remote, sh -c). Leave it to Marc (docs/ORCHESTRATION.md, "One-time',
            'setup", step 4). Branches push with git -C <worktree> push -u origin',
            "<branch>.",
        ]
    return "\n".join(
        [
            "Refused by the fork gh guard (.claude/hooks/fork_gh_guard.py, MAR-263):",
            f"  {shown}",
            f"{_DENIED_MARK}, wherever it runs and whatever --repo or -R says:",
            *_DENIALS[kind],
            *footer,
        ]
    )


def _when_in_doubt(command: str, starts: list[str], problem: str) -> str | None:
    """Return a refusal for a command the hook couldn't analyse, or ``None``."""
    if _GH_DENIED.search(command) or _GIT_DENIED.search(command):
        return "\n".join(
            [
                "Refused by the fork gh guard (.claude/hooks/fork_gh_guard.py,"
                " MAR-263):",
                f"the hook couldn't analyse this command ({problem}),",
                f"and it looks like a command that {_DENIED_MARK}:",
                "gh release create/new/edit/upload/delete, gh workflow run/enable/",
                "disable, gh repo create/new/delete/edit/fork/sync/archive/",
                "unarchive/rename, gh repo deploy-key add/delete, gh repo autolink",
                "create/new/delete, gh pr merge --admin, gh alias set/import,",
                "gh extension install, gh skill install/add/update/publish,",
                "gh copilot, gh gist create/new/edit/rename/delete, gh agent-task",
                "create, gh config set editor/pager/browser, gh auth token/login/",
                "logout/refresh/switch/setup-git/git-credential, a rerun in a fork,",
                "gh followed by an expansion, a gh command that names a RiskThinking",
                "repository,",
                "git tag, git update-ref on refs/tags, or a git push of tags, of",
                "every branch (--all, --branches, --prune) or to main or parametric,",
                "git submodule foreach, git credential, git rebase --exec, git",
                "filter-branch, or a variable that sets git's configuration",
                "(GIT_CONFIG_*).",
                'Those are Marc\'s (docs/ORCHESTRATION.md, "One-time setup",',
                "step 4). If it is none of them, split it into simpler commands.",
            ]
        )
    if not _GH_CHECKED.search(command):
        return None
    if not (any(under_forks(s) for s in starts) or _FORKISH.search(command)):
        return None
    return "\n".join(
        [
            "Refused by the fork gh guard (.claude/hooks/fork_gh_guard.py, MAR-253):",
            f"the hook couldn't analyse this command ({problem}),",
            "and it may run a repo-scoped gh command in a CRC fork (gh",
            f"{_CHECKED_LIST}).",
            "Fix: split it into simpler commands, pass"
            f" --repo {OWNER}/<fork> to every such gh command",
            f"(e.g. gh pr checks <n> --repo {OWNER}/crc-sdk), and in gh api write"
            f" the repository out (repos/{OWNER}/<fork>/...).",
        ]
    )


def decide(command: str, starts: list[str], home: str) -> str | None:
    """Return the refusal message for a shell command, or ``None`` to allow it.

    A command the hook can't parse is refused only if it may run a checked
    gh subcommand in a fork path.

    Parameters
    ----------
    command
        The tool's ``command``.
    starts
        The directories the command may start in.
    home
        The home directory, for ``~`` and ``$HOME``.

    Returns
    -------
    str or None
        Why the call is refused, or ``None``.
    """
    try:
        return evaluate(command, starts, home)
    except ParseError as exc:
        return _when_in_doubt(command, starts, str(exc))


def terminal_starts(
    tool_cwd: object, cwd: str, project_dir: str | None, home: str
) -> list[str] | None:
    """Return the directories a terminal-tool command may start in.

    The terminal tool starts its shell in its own ``cwd``: absolute, ``~``, or
    relative to the session's working directory, which is also the default.
    The hook can't tell which directory the tool takes as the session's, so
    it takes both the hook input's ``cwd`` and ``CLAUDE_PROJECT_DIR``.

    Parameters
    ----------
    tool_cwd
        The tool input's ``cwd``, if any.
    cwd
        The hook input's ``cwd``, absolute.
    project_dir
        ``CLAUDE_PROJECT_DIR``, if set.
    home
        The home directory, for ``~``.

    Returns
    -------
    list of str or None
        The possible start directories, or ``None`` if ``tool_cwd`` is
        neither missing nor a string.
    """
    bases = [cwd] + ([project_dir] if project_dir else [])
    if tool_cwd is None or tool_cwd == "":
        return bases
    if not isinstance(tool_cwd, str):
        return None
    path = tool_cwd
    if path == "~" or path.startswith("~/"):
        path = home + path[1:]
    elif path.startswith("~"):
        path = os.path.expanduser(path)
    if os.path.isabs(path):
        return [path]
    return [os.path.join(base, path) for base in bases]


def fail_closed_for_gh(text: str, problem: str) -> int:
    """Handle a failure of the hook itself: refuse checked gh, pass the rest.

    Used when the input can't be read or the hook raises. It only looks for
    the word ``gh`` followed by a checked subcommand in ``text``
    (``_GH_CHECKED``), or text that looks like a denied gh or git command
    (``_GH_DENIED``, ``_GIT_DENIED``), so it doesn't depend on the code that
    failed.

    Parameters
    ----------
    text
        The shell command, or the raw hook input if the command is unknown.
    problem
        What went wrong.

    Returns
    -------
    int
        The exit status: 2 if ``text`` mentions gh with a checked subcommand
        or looks like a denied gh or git command, else 0.
    """
    if not (
        _GH_CHECKED.search(text) or _GH_DENIED.search(text) or _GIT_DENIED.search(text)
    ):
        return 0
    if len(problem) > 200:
        problem = problem[:197] + "..."
    lines = [
        "Refused by the fork gh guard (.claude/hooks/fork_gh_guard.py, MAR-253):",
        f"fork_gh_guard failed internally ({problem});",
        f"refusing this repo-scoped or denied gh command (gh {_CHECKED_LIST},",
        "or a gh write that .claude/settings.json denies), or a git command that",
        "makes or pushes a tag, pushes every branch or a shared branch, reads a",
        "credential, runs a shell string this hook can't read, or changes git's",
        "settings through the environment. Other commands pass.",
        "Fix: report the error to the orchestrator, so that the hook is fixed and",
        "a case added to scripts/check_fork_gh_guard.py. Meanwhile a simpler form",
        f"may get through: one gh command per Bash call, with --repo {OWNER}/<repo>.",
    ]
    sys.stderr.write("\n".join(lines) + "\n")
    return 2


def main() -> int:
    """Run the hook: read the input on stdin, exit 2 to refuse, 0 to allow.

    Bash and Monitor commands start in the hook input's ``cwd``, terminal-tool
    commands in ``terminal_starts``. Other tools, and a Monitor WebSocket
    watch, pass. Any failure (input that isn't a ``PreToolUse`` JSON object
    with a ``tool_input.command``, or an exception) goes to
    ``fail_closed_for_gh``.

    Returns
    -------
    int
        The exit status: 2 if the call is refused, 0 otherwise.
    """
    text = ""  # what a failure is judged on: the raw input, then the command
    try:
        text = sys.stdin.read()
        payload = json.loads(text)
        if not isinstance(payload, dict):
            return fail_closed_for_gh(text, "the hook input is not a JSON object")
        tool = payload.get("tool_name", "Bash")
        if tool not in SHELL_TOOLS and tool != TERMINAL_TOOL:
            return 0
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            tool_input = {}
        if tool == "Monitor" and "command" not in tool_input and "ws" in tool_input:
            return 0  # a WebSocket watch runs no shell command
        command = tool_input.get("command")
        if not isinstance(command, str):
            return fail_closed_for_gh(text, "the hook input has no tool_input.command")
        text = command
        default_cwd = os.getcwd()
        cwd = payload.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            cwd = default_cwd
        cwd = os.path.join(default_cwd, cwd)
        home = os.environ.get("HOME") or os.path.expanduser("~")
        starts: list[str] | None = [cwd]
        if tool == TERMINAL_TOOL:
            project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or None
            starts = terminal_starts(tool_input.get("cwd"), cwd, project_dir, home)
        if starts is None:
            return fail_closed_for_gh(text, "the terminal tool's cwd is not a string")
        message = decide(command, starts, home)
    except Exception as exc:  # the hook failed: refuse checked gh commands only
        return fail_closed_for_gh(text, f"{type(exc).__name__}: {exc}")
    if message is None:
        return 0
    sys.stderr.write(message + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
