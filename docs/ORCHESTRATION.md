# Orchestrator runbook

You coordinate the **parametric-insurance-design** program. You plan, delegate issues to worker subagents, review, merge, and **keep Linear true**. You never do Human work. Workers follow [`AGENTS.md`](../AGENTS.md). The owner is Marc Prinzing.

## Operating model

- **Autonomous.** Marc starts an orchestrator session by hand, in auto mode, with `/orchestrate` (or `/loop /orchestrate` to keep it waking up while it waits on him). From then on the orchestrator runs the loop below on its own: it dispatches, reviews, merges and keeps Linear current. It contacts Marc only for hard blocks and Human work (see "Owner alerts").
- **Three repositories** (D9, Marc, 2026-11-05):
  - `marc272/parametric-insurance-design`, this repository: the reference implementation and test oracle, the design record (ADR 0005), the CLIMADA prototype and the paused tracks. Branches from `main`.
  - `marc272/crc-sdk`, a fork of `RiskThinking/crc-sdk`: where `crc_sdk.parametric` is built. Branches from, and PRs into, `parametric`.
  - `marc272/crc-docs`, a fork of `RiskThinking/crc-docs`: the showcase notebook. Branches from, and PRs into, `parametric`.

  Each fork's `main` mirrors upstream and is never pushed to. Nothing goes to RiskThinking's repositories: the upstream PRs are Marc's (MAR-249). Workers in the forks follow `AGENTS.md`, "Working in the CRC forks".
- **Stateless and resumable.** Everything needed to continue lives in Linear (statuses, dispatch records, status updates), git and GitHub, never in one conversation. After a usage-limit reset or a crash, `continue` in the same session, or `/orchestrate` in a new one, resumes the work (see "Resuming after an interruption").
- **One orchestrator at a time.** Don't start a second orchestrator session while one is active.

### One-time setup (owner)

These steps are done by Marc, because agents may not change their own permissions.

1. **Let the auto-mode classifier accept orchestrator merges.** By default it blocks "merging a PR no human has approved". The classifier ignores `autoMode` in project settings, so merge this block into `~/.claude/settings.json`:

   ```json
   "autoMode": {
     "environment": [
       "$defaults",
       "Organization: Marc Prinzing, solo owner. Primary use: building the open-source parametric-insurance-design program, run by an orchestrator agent that delegates to worker subagents",
       "Source control: github.com/marc272 (the owner's own GitHub account). marc272/parametric-insurance-design is a public repository the owner created for this work. marc272/crc-sdk and marc272/crc-docs are the owner's forks of RiskThinking/crc-sdk and RiskThinking/crc-docs, where agents build the CRC module on the branch `parametric`",
       "Key services: the owner's Linear workspace 'Marc prinzing' (team MAR), reached through the Linear connector, is the program's tracker. Agents create and update issues, comments and project status updates there as part of the documented workflow (docs/ORCHESTRATION.md)"
     ],
     "allow": [
       "$defaults",
       "Agent PR merges in marc272/parametric-insurance-design: on 2026-10-25 the owner, Marc Prinzing, authorised the orchestrator agent to squash-merge PRs (`gh pr merge <n> --squash`) without a human approval, after it has reviewed the PR and all CI checks are green (see the repository's CLAUDE.md and docs/ORCHESTRATION.md 'Merge policy'). This does not cover admin merges, force pushes, direct pushes to main, or a worker merging its own PR",
       "Agent PR merges in the forks marc272/crc-sdk and marc272/crc-docs: on 2026-11-05 the owner authorised the orchestrator agent to squash-merge PRs into the branch `parametric` (`gh pr merge <n> --repo marc272/<fork> --squash`) under the same conditions, and to keep `parametric` current by merging upstream `main` into it through a sync PR merged with `--merge`. This does not cover admin merges, force pushes, pushes to any main, or any action on RiskThinking's repositories"
     ]
   }
   ```

   While Actions minutes are exhausted, "all CI checks are green" in this text is met by the local-CI fallback (see "Merge policy", "Fallback: local CI while Actions minutes are exhausted"). The block itself doesn't need to change.

2. **Start sessions in auto mode, in this repository, with the forks folder added:** `claude --add-dir /Users/marcprinzing/Parametric_Insurance/forks` from the main checkout, or `/add-dir /Users/marcprinzing/Parametric_Insurance/forks` in the session. Without auto mode every command prompts and the loop stalls. Claude Code loads permission rules only from the primary working directory's `.claude/settings.json`, never from an added directory. A session started in this repository therefore gets the deny rules below; a session started in the workspace root reaches the forks but runs without them.
3. **Optional: phone alerts.** Connect Remote Control, so that `PushNotification` reaches your phone as well as the desktop.
4. **Guardrails, already checked in.** `.claude/settings.json` denies, in every mode:
   - force pushes;
   - pushes to `main`, ours or a fork's, and to a fork's `parametric`, which changes only through merged PRs (`refs/heads/<branch>` too, MAR-355), and `git push --all`, its alias `--branches` and `--prune` (MAR-343): the first two push a local `main` and `parametric` too, and `--prune` deletes remote branches. `git fetch --prune` stays allowed;
   - pushes to the `upstream` remote, and any `gh` command that names a RiskThinking repository: `RiskThinking/<repo>` anywhere in it, in `--repo`, `-R`, a URL, `gh api` or a body passed inline (pass bodies with `--body-file`);
   - admin merges (`--admin`, `--admin=<value>`);
   - creating, forking, syncing, editing, archiving, unarchiving, renaming or deleting repositories (`gh repo new` is `gh repo create`);
   - tags and releases: `git tag`, `git update-ref` on `refs/tags` or with `--stdin`, pushing tags (`--tags`, `--follow-tags`, `--mirror`, a `refs/tags/` refspec, or a refspec that starts with `v`, quoted or not, to any remote), `gh release create` (alias `new`), `edit`, `upload` and `delete`, `gh skill publish` (it creates a tag and a release), and the matching `gh api` calls;
   - running, enabling or disabling workflows by hand (`gh workflow run`, `enable`, `disable`, `gh api …/dispatches`, `gh api …/actions/workflows/<id>/enable` and `/disable`), and rerunning a run in a fork (`gh run rerun` with a `crc-sdk` or `crc-docs` repo flag, and the `gh api …/actions/runs/<id>/rerun` endpoints there): a rerun of crc-sdk's Package release run publishes again. To rerun a fork PR's CI, push a commit to its branch;
   - changing Actions on the forks: a `gh api` `PUT` to `actions/permissions` of `marc272/crc-docs`, where upstream's `live` job would reach RiskThinking's data if Actions came on (MAR-306), or of `marc272/crc-sdk`, where turning them off would remove the merge gate (MAR-343). Reading the setting stays allowed;
   - new `gh` commands and other agents: `gh alias set` and `import`, `gh extension install` (also `gh ext`, `gh extensions`), `gh skill install` (alias `add`) and `update` (also `gh skills`), `gh copilot`, which runs the Copilot CLI, and `gh agent-task create` (also `gh agent`, `agents`, `agent-tasks`), which starts a Copilot coding agent that pushes branches and opens PRs;
   - repository settings, and publishing outside our repositories: `gh repo deploy-key add` and `delete` (a write key is a new push credential), `gh repo autolink create` (alias `new`) and `delete`, the matching `gh api` calls (`repos/…/keys`, `repos/…/autolinks`, reads included), and `gh gist create` (alias `new`), `edit`, `rename` and `delete`, and `gh api` on `gists` (reads included);
   - `gh auth token`, `gh auth git-credential` and `gh auth status --show-token`, which print a credential; `gh auth login`, `logout`, `refresh`, `switch` and `setup-git`, which sign in or change the account or credential that `gh` and `git` use (MAR-343); and `gh config set editor`, `pager` and `browser`, each naming a program that `gh` runs later;
   - `git submodule foreach`, which runs a shell string in each submodule (MAR-343);
   - `git credential` and the `git credential-<helper>` commands, which can print the token that `gh auth token` would, and `git rebase --exec` (`-x`) and `git filter-branch`, which run shell strings that neither these rules nor the hook read (MAR-355). `git rebase` without them stays allowed;
   - the app tools that start processes or move the session (Marc's decision on MAR-263's survey, MAR-282): the Browser pane's `preview_start`, which runs whatever `.claude/launch.json` holds; the iOS Simulator tools (`mcp__Claude_Code_iOS_Simulator__*`); `change_directory`, because the session would run on without these settings; and computer use (`mcp__computer-use__*`). Also their names in a cloud session linked to this computer (`mcp__remote-devices__Claude_Browser__preview_start`, `mcp__remote-devices__computer_*`). **The `preview_start` rules are lifted when the website work resumes:** Marc removes them then, and agents run dev servers with Bash `run_in_background` meanwhile;
   - the routes to a GitHub merge or approval that start no process (Marc's decision on MAR-282, MAR-289): `set_auto_merge` (`mcp__*__set_auto_merge`); the Linear connector's `merge_diff` and `submit_diff_review` (`mcp__*__merge_diff`, `mcp__*__submit_diff_review`), which accept a GitHub PR; Claude in Chrome (`mcp__claude-in-chrome__*`), which acts with your GitHub sign-in; and the `engineering` plugin's GitHub tools (`mcp__plugin_engineering_github__*`). The rest of the Linear connector stays, so the orchestrator keeps reading and writing issues, comments and status updates. The Browser pane has no such rule: never sign in to GitHub there ("You never" below).

   The `gh` rules cover `-R`/`--repo` before the group (`gh -R <repo> release create`) and between the group and the command (`gh release -R <repo> create`) too (MAR-263). Agents never need these: releases and tags are Marc's, and CI runs on push and pull request. To read tags, use `git for-each-ref refs/tags` or `git ls-remote --tags origin`. Our Site workflow's manual trigger stays Marc's, from the Actions page.

   The rules match the command text, so they catch the usual forms, `git -C <path> push …` included, but not every way of writing a command. They are a backstop for the rules in `AGENTS.md`, not a replacement. The `-R` rules also deny some harmless commands: a `gh -R <repo> …` command whose title or inline body has a phrase such as "workflow run", "release create" or, with a fork's `-R`, "run rerun", and `gh release -R <repo> view … --json createdAt`. The `v*` push rules also deny a branch whose name starts with `v`, so keep to the branch names the issues give. The `git -C` rules match the whole text, so a `git -C <path> commit` whose message has a phrase such as `rebase --exec`, `filter-branch` or `credential fill` is denied too (MAR-355): reword it. Pass bodies with `--body-file`, and `-R` after the command.

   A `PreToolUse` hook on the tools that run shell commands (Bash, Monitor and the desktop app's terminal tool), [`.claude/hooks/fork_gh_guard.py`](../.claude/hooks/fork_gh_guard.py) (MAR-253, MAR-261, MAR-263, MAR-282, MAR-289), adds what the rules can't express, and says what to do instead:
   - **Tags through git, everywhere** (MAR-289): a pushed `v*` tag runs crc-sdk's Package release. It refuses the tag commands above in every spelling, `git` by path or in quotes, after `-C` or `-c`, inside `sh -c`, and flags abbreviated as git allows (`--mirr`). It also refuses `git push` from `xargs`, `git send-pack`, `git remote add --mirror`, and setting `push.followTags`, `remote.<name>.push`, `remote.<name>.mirror` or `alias.<name>` (`-c`, `--config-env`, `git config`), which would make a plain push carry tags. A push operand or flag name from an expansion is refused too (`git push origin "$TAG"`, `git push --$X`): write the branch out. `git -C "$WT" push -u origin <branch>` passes. Tags made another way stay local until pushed, and the push is what these checks stop.
   - **Every branch, and git settings from the environment, everywhere** (MAR-343): it refuses `git push --all`, `--branches` and `--prune` in the same spellings, abbreviations included (`--al`, `--b`, `--pru`), the matching refspec (`git push origin :`), and setting `push.default`, which can make a plain push do the same. It refuses a command's leading assignment to, or `env` or `export` of, `GIT_CONFIG_COUNT`, `GIT_CONFIG_KEY_<n>`, `GIT_CONFIG_VALUE_<n>`, `GIT_CONFIG_PARAMETERS`, `GIT_CONFIG_GLOBAL`, `GIT_CONFIG_SYSTEM` or `GIT_CONFIG`, which reach the settings above past `-c` and `git config`. `GIT_CONFIG_NOSYSTEM` passes, and so does the name as a plain word (`grep GIT_CONFIG_COUNT= …`).
   - **Shared branches, credentials and shell strings in git, everywhere** (MAR-355): it refuses a `git push` whose destination is `main` or `parametric`, in any spelling: `refs/heads/<branch>`, `heads/<branch>`, `<src>:<branch>` or `<branch>:`, with `git` by path or after `-c` or `-C`, inside `sh -c`, to any remote. It reads only the command, so `git push` alone and `git push origin HEAD` name no branch and pass: they are for a worker branch, never for a checkout of `main` or `parametric`. Pushing *from* one (`git push origin main:<other>`) and every `git fetch` pass. It also refuses `git credential` and `git credential-<helper>`, `git rebase --exec` in every form git accepts (`-x`, `--ex`, `-ix`), `git filter-branch`, and `HOME=` or `XDG_CONFIG_HOME=` set for a git command, which pick git's per-user settings as `GIT_CONFIG_GLOBAL` does. Other programs may set those two (`HOME=/tmp/x uv run pytest`).
   - **Everywhere**, it refuses the denied `gh` commands above in every spelling: the repo flag anywhere, `gh` by path or in quotes, a group's alias (`gh ext`, `gh skills`), inside `sh -c`, and RiskThinking in any case. It also refuses a `gh run rerun` without a repo flag in a fork path, a `gh` command whose subcommand, or whose command in a group with denied commands, comes from an expansion (`gh $c …`, `gh release "$x" …`, `gh release cre{ate,} …`), `gh` or `git` itself from a variable when the rest is a denied command (`$GH release create …`), and an expansion among `gh pr merge`'s flags (`gh pr merge 3 $X`): neither layer can tell what that runs. Write them out. A PR number, run ID or tag from a variable is fine (`gh pr checks "$PR"`), and so is a `--subject` or `--body` value, but `gh` as a plain word followed by an expansion is refused too (`grep gh "$f"`).
   - **In a fork path** (its working directory, or a `cd` or `git -C` target, under `/Users/marcprinzing/Parametric_Insurance/forks/`), it refuses any command of a `gh` group that takes the repository from the clone and lacks `--repo marc272/<fork>` or `-R marc272/<fork>`: the groups with a group-level `-R`, `browse`, `cache`, `co`, `discussion`, `issue`, `label`, `pr`, `release`, `ruleset` (alias `rs`), `run`, `secret`, `variable` and `workflow`, and the other commands with their own `-R` that do the same: `gh agent-task create` and `view`, `gh project link` and `unlink`, and `gh repo autolink`, `deploy-key`, `read-dir` and `read-file` (MAR-282). It refuses `gh repo view` there without a `marc272/<fork>` argument, and any `gh api` call with `{owner}`/`{repo}` placeholders (write `repos/marc272/<fork>/…` instead). `gh` from a variable gets the same check (`$GH pr list`, MAR-343), but `run` and `cache` only with one of `gh`'s own commands after them, so `$UV run pytest` and `$UV cache clean` pass. A whole command from a variable (`"$CMD"`) can't be read.

   If the hook fails internally, it refuses any command that mentions `gh` followed by one of those subcommands, or that looks like a denied `gh` or `git` command, and lets the rest through; if `python3` is missing, the hook can't start, and Claude Code, treating that as a non-blocking error, runs every command. The deny rules also refuse setting `GH_REPO` in a command (`GH_REPO=…`, `env GH_REPO=…`, `export GH_REPO…`), so only `--repo` or `-R` picks the repository, and they remove the terminal tool (`mcp__terminal__run_in_terminal`), whose commands run in your login shell outside every Bash rule: agents use Bash (with `run_in_background` for long commands) or Monitor, which follows the Bash rules. `scripts/check_fork_gh_guard.py`, in CI's lint job, tests both hooks and their wiring, the deny rules on the denied forms and the prescribed commands, and the app-tool rules on the tools they remove and keep, matched as the permissions page says Claude Code matches them.

   Two more app tools that start sessions stay available. `start_session`, which "Delegating to subagents" uses, has its own `PreToolUse` hook, [`.claude/hooks/session_guard.py`](../.claude/hooks/session_guard.py) (Marc's decision on MAR-282, MAR-289): it refuses a call that sets `cwd`, `host`, `preset`, `environment` or `repository` to anything non-empty, or a `target` other than `"local"`, and it refuses any call it can't read. A deny rule can't do this, because settings skip `mcp__` rules with parentheses. The scheduled tasks stay under a review rule: not at all (Marc, 2026-11-06; "You never" below).

## Ground truth

- **Linear** (workspace "Marc prinzing", team MAR) is the source of truth for what we aim to do, priorities, plan, decisions and status. The entry point is the [Program hub](https://linear.app/marc-prinzing/project/program-hub-1b757250497c): its description (mission, outputs, phases, scheduling and publication rules, decision index) and its status updates (where we are).
- `docs/SPEC.md` is the source of truth for the *how*. ADRs record technical decisions.
- If reality, a file and Linear disagree, find out what is true, then fix Linear (or the file) in the same session. **Keeping Linear current is part of your job, not an afterthought.**

## Session start

1. Read the Program hub description and its latest status update.
2. List the team's issues that are **In Progress** and **In Review**. Reconcile each with git and PR state, in this repository and in both forks:
   - is a PR merged without the issue being Done?
   - is a worker gone while its issue is still In Progress?

   Fix Linear first. Resume or re-dispatch interrupted work as described in "Resuming after an interruption".
3. Read new comments since the last status update, especially on Human issues: the owner may have answered.
4. In each fork, check whether upstream `main` has moved past `parametric` (see "Keeping `parametric` current").
5. Rebuild the ready set (see "The loop") and decide this session's dispatches.

## Session end

Before stopping, even after an interruption:

- Every issue's status matches reality. No In Progress issue is left without an active worker; move those back to Todo with a comment.
- Every merged PR is linked in a comment on its issue.
- Every follow-up a worker reported is filed as an issue: project, milestone, blockers, acceptance criteria. Or it is explicitly declined, with a comment saying why.
- If anything moved, post a **status update on the Program hub**:
  - Done since last update;
  - in flight;
  - next on the critical path;
  - Human queue;
  - risks and blockers;
  - health (onTrack / atRisk / offTrack).
- Update a project's status (Planned → In Progress → Completed) when its work starts or ends.

## Linear conventions

**Statuses**

| Status | Meaning |
|---|---|
| Backlog | Not ready: blocked, or waiting for refinement |
| Todo | Ready: every "blocked by" issue is Done |
| In Progress | Dispatched to exactly one worker, or the human is acting on a Human issue |
| In Review | PR open, or prepared material waiting for human approval |
| Done | Merged (agent issues) or closed by the human (Human issues) |
| Canceled | Dropped, with a comment saying why (e.g. MAR-35 if D6 = no) |

**Labels**

- **Human:** never dispatched for completion. You may dispatch only the "Agent may prepare" part from the issue's "Agent vs. human" section. Then set the issue to In Review, assign it to Marc Prinzing, and wait. Only the human marks it Done, unless the owner explicitly delegates the decision to you in the conversation; record that on the issue.
- **Gate:** downstream work stays blocked until the human marks it Done (MAR-18 parity, MAR-29 checkpoint C1).
- **Decision:** one of D1–D10. Always also Human. The outcome is recorded on the issue, and technical outcomes also get an ADR.
- **Spike, Research, Feature, Chore:** informational.

**Containers.** An issue with sub-issues (MAR-17, MAR-18, MAR-19) is never dispatched. Mark it Done when all its sub-issues are Done. For a Human container (MAR-18), set it to In Review with the assembled result and let the human close it.

**Scope.** Only issues in the program's projects count. Ignore issues without a project, such as Linear's onboarding issues MAR-1 to MAR-4.

**Keeping Linear true**

- Every piece of work maps to an issue. If you or a worker discover new work, file it immediately (project, milestone, blockers, acceptance) rather than carrying it in your head.
- When an issue's scope changes, edit its **description**. A comment alone is not enough, because the description is what the next worker reads.
- Decisions are recorded on their Decision issue. Then `docs/SPEC.md` §11 or an ADR is updated through a small PR before dependent work is dispatched.
- After any change to the spec or the plan, check open issues in **all** projects for impact, and update them.

## Scheduling across streams

The Program hub sets these rules (from 2026-11-05):

1. **CRC first.** Ready CRC Contribution issues get worker slots first, in milestone order: R1 → R2 → R3 → R4.
2. **CLIMADA when CRC has no ready agent work**, e.g. while CRC waits on Marc. Only then does a CLIMADA Contribution issue get a slot.
3. **No dispatches from paused projects.** Issues in Foundation, Website & Blog and Paper are not dispatched, even in Todo, until Marc resumes a project. Their open PRs (#165, #7, #170) stay as they are, with no rebases and no merges. Fixing a red `main` is still allowed.
4. **Raise Human issues early** when they sit on the CRC path: MAR-242 (the forks), MAR-244 (approving ADR 0005), and MAR-249 Part A (the questions for RiskThinking).
5. **New work gets its own issue.** The Linear workspace was upgraded on 2026-11-05, so the free plan's issue limit no longer applies.
6. **Publication rule:** review every external-facing deliverable, the CRC module's docs and notebook included, against the publication rule decided at C1 (MAR-29), as stated in [`AGENTS.md`](../AGENTS.md) and SPEC §1: RQ1 conditional, mechanism-based statements only; RQ2 and anything involving joint calibration method only.

## The loop

1. **Sync.** Do the session-start steps, then move Backlog → Todo for every issue whose blockers are all Done.
2. **Pick.** Leaf issues in Todo without the Human label, outside the paused projects, ordered by the scheduling rules above, then priority, then milestone. Constraints:
   - at most **3 workers** at once (4 when the lanes are clearly independent), counted across all three repositories;
   - no two concurrent issues may own the same module (ADR 0002 ownership map; in crc-sdk, the module layout in ADR 0005);
   - serialise anything that touches `pyproject.toml`, lockfiles (`uv.lock`, `packages/climada/pixi.lock`) or CI config, in each repository. A change to the core's dependencies must also run `pixi lock` in `packages/climada` and commit `pixi.lock`, because the climada CI job installs with `--locked` (ADR 0002 §10, MAR-71).
3. **Check size.** If an issue is clearly more than one PR (several modules, or more than about a day of work), first split it into sub-issues with goal, scope, acceptance and blockers. The original becomes a container. Don't pre-split far-future work; split when it becomes ready.
4. **Delegate** (see below). Set the issue to In Progress and post a **dispatch record** on it.
5. **Review.** When a worker reports back, check:
   - CI is green (or the local-CI fallback, see "Merge policy");
   - every acceptance criterion is evidenced in the PR body;
   - the diff stays within the owned files, with no stray interface or dependency changes;
   - tests exercise the behaviour, beyond a smoke test;
   - `packages/climada` doesn't import `packages/crc`;
   - Research issues are reproducible from the recorded config hashes;
   - external-facing work follows the publication rule.

   For a fork PR, also check:
   - the base is `parametric`, and the fork's own checks pass (see "Merge policy"; in crc-docs, where Actions are off, the local checks on the final head, see "Fork PRs");
   - no file of the diff imports `parametric_insurance_design`;
   - no MAR IDs or Linear links in code or docs (`git -C <worktree> diff origin/parametric... | grep -nE 'MAR-[0-9]+|linear\.app'` prints nothing); commit subjects are conventional, each with a `Refs: MAR-<n>` trailer;
   - nothing new in crc-sdk's base dependencies (`[project].dependencies`): the solver sits in an optional extra, as ADR 0005 chooses;
   - no data committed; tests are offline, on small synthetic fixtures;
   - no breaking change to anything exported in `__all__`;
   - the fork's own `AGENTS.md` rules hold (crc-sdk: no I/O in builders or `explain()`, atomic writes, licence and provenance for every source).

   Request changes from the same worker, which keeps its context. After two failed rounds, escalate to the human. For core numerical code, an independent reviewer subagent is worth the cost.
6. **Merge.** Follow the "Merge policy" below: squash-merge agent PRs that pass review, in dependency order, updating dependent branches when needed. Shared branches (`main`, `parametric`) are never rebased. Set the issue to Done, comment with the PR link, and file the reported follow-ups.
7. **Repeat** from step 1. End the session with the session-end steps.

## Delegating to subagents

**One issue = one worker = one branch = one PR.** Each worker gets its own git worktree, on the issue's Linear branch name: cut from the latest `main` in this repository, or from the fork's `parametric` in a fork. For an issue in this repository, in Claude Code, either:

- spawn a subagent per issue with worktree isolation. Its report comes back to you, which is the default; or
- start a separate session per issue when the owner wants to follow that work directly.

For an issue in a fork, see "Worker worktrees in the forks" below. Workers may not have the Linear connector. You stay responsible for Linear in every case.

### Worker worktrees in the forks

The `Agent` tool's `isolation: "worktree"` makes worktrees of this repository only. For an issue in a fork, you create the worktree in the fork clone yourself and spawn the worker without isolation. The session needs the forks folder as a working directory ("One-time setup", step 2).

The fork clones (R-10, MAR-242) are `/Users/marcprinzing/Parametric_Insurance/forks/crc-sdk` and `/Users/marcprinzing/Parametric_Insurance/forks/crc-docs`. Worker worktrees go next to them, at `/Users/marcprinzing/Parametric_Insurance/forks/worktrees/<fork>-mar-<n>`, so they sit outside both clones.

1. **Check the clone, once per session.** In each clone, `git -C <clone> remote get-url --push upstream` prints `DISABLED`, and `gh repo set-default --view`, run in the clone, prints `marc272/<fork>`. If either fails, dispatch no fork work: R-10's set-up is Marc's, so alert him.
2. **Create the worktree:**

   ```bash
   git -C <clone> fetch origin
   git -C <clone> worktree add --no-track -b <gitBranchName> <worktree> origin/parametric
   ```

   `--no-track` keeps the new branch from tracking `parametric`. The worker's first push sets its upstream.
3. **Spawn the worker** with `Agent`, `run_in_background: true` and no `isolation`, using the fork brief below with the worktree path.
4. **Post the dispatch record** with the repository and the worktree path.

Every `gh pr` command on fork work, yours and the workers', passes `--repo marc272/<fork>` explicitly: in a fork clone, `gh` without it can resolve to RiskThinking's repository. Read upstream only through `git fetch upstream`; `gh` commands that name a RiskThinking repository are denied.

Agents never create tags or run workflows by hand in the forks. crc-sdk's workflows are enabled (Marc, 2026-11-05), and its `release.yaml` ("Package release") runs on any pushed `v*` tag and on `workflow_dispatch`, with `id-token: write`. A tag or a manual run could publish a release. crc-docs' Actions are off, and stay off (see "Fork PRs").

### Briefs

**Brief template.** Paste the issue text verbatim; don't paraphrase acceptance criteria. Keep the line on logs and drafts: workers write them inside their own worktree, never in the shared session scratchpad, where concurrent workers overwrote each other's files on 2026-10-27.

```text
You are a worker on the parametric-insurance-design program. AGENTS.md is binding.

Issue: MAR-<n>, <title> (<Linear URL>)
Why it matters: <one line linking it to the output it unblocks>

--- Issue description (verbatim) ---
<goal, scope, acceptance criteria>
---

Read first: docs/SPEC.md §<…>; docs/adr/0002 (ownership map); <merged PRs of the blockers>
You own: <files from the ownership map>. Import anything; edit nothing else.
Branch: <Linear gitBranchName>, from the latest main, in your own worktree.
Push early: push the branch after your first commit, open a draft PR, and push after every meaningful commit, so your work survives an interrupted session.
Keep logs and PR-body drafts inside your own worktree (the gitignored results/), never in the shared session scratchpad.
Done means: PR open (marked ready), CI green, every acceptance criterion evidenced in the PR body.
Report back: PR link, summary, anything unverified, follow-ups you discovered, open questions.
Don't change Linear; the orchestrator keeps it current. Never merge.
```

**Fork brief template.** For an issue in `marc272/crc-sdk` or `marc272/crc-docs`. The fork has no ignored `results/`, so logs and drafts go in a folder next to the worktree.

```text
You are a worker on the parametric-insurance-design program, in the fork marc272/<fork>.
AGENTS.md of parametric-insurance-design is binding, and so is the fork's own AGENTS.md.
Read "Working in the CRC forks" in the former first.

Issue: MAR-<n>, <title> (<Linear URL>)
Why it matters: <one line linking it to the output it unblocks>

--- Issue description (verbatim) ---
<goal, scope, acceptance criteria>
---

Repository: marc272/<fork>. Worktree: <absolute path>, on branch <gitBranchName>, cut from origin/parametric.
Work only in that worktree: absolute paths, git -C <worktree> for git, cd <worktree> && … for uv.
Edit nothing else: not parametric-insurance-design, not the fork clone's own checkout.
Read first: <worktree>/AGENTS.md; docs/adr/0005 in parametric-insurance-design; <merged PRs of the blockers>
You own: <files or modules in the fork>. Import anything except parametric_insurance_design; edit nothing else.
Commits: conventional-commit subjects (feat(parametric): …), no MAR IDs or Linear links in code or docs, and a "Refs: MAR-<n>" trailer in the final paragraph, with any Co-Authored-By line next to it and no blank line between them.
Push early: git -C <worktree> push -u origin <gitBranchName>, then
gh pr create --repo marc272/<fork> --base parametric --head <gitBranchName> --draft, titled "[MAR-<n>] <conventional subject>".
Every gh pr command passes --repo marc272/<fork>. Never push to upstream, main or parametric; never contact RiskThinking.
Checks: <the fork's checks, as AGENTS.md "Their rules are binding" gives them>. Paste their summary on the final head into the PR body.
Keep logs and PR-body drafts in <worktree>-notes/, never in the worktree or the shared session scratchpad.
Done means: PR open (marked ready), the fork's checks green, every acceptance criterion evidenced in the PR body.
Report back: PR link, summary, anything unverified, follow-ups you discovered, open questions.
Don't change Linear; the orchestrator keeps it current. Never merge.
```

**Resume brief.** Use this when a worker is gone but its branch or draft PR exists. Put this before the normal brief:

```text
You are resuming interrupted work. Branch <name> already exists (PR #<n>, if any).
Check it out in your worktree (git fetch && git switch <name>), read its commits and the PR body,
and continue from there. Don't restart from main, and don't rewrite pushed history.
Still to do, as far as the orchestrator knows: <list>.
```

For a fork, reuse the old worktree if `git -C <clone> worktree list` still shows it. Otherwise make a new one on the existing branch, `git -C <clone> worktree add <worktree> <branch>`, and put its path in the resume brief ("Don't restart from parametric").

## Dispatch record

Every dispatch, re-dispatch or resume posts one comment on the issue, so that a later session can find and resume the work:

```text
Dispatch record
- worker: <agent ID or session link>, started <ISO time>
- repository: <marc272/parametric-insurance-design | marc272/crc-sdk | marc272/crc-docs>
- branch: <gitBranchName>   worktree: <path, if known>
- PR: <link, or "none yet">
- notes: <resume of …, review round n, anything a successor needs>
```

Update the record with a new comment when the PR opens, and at each review round.

## Merge policy

Marc authorised agent merges on 2026-10-25 ("PR should be merged automatically in general", MAR-80). On 2026-11-05 he extended this to PRs into `parametric` in the forks `marc272/crc-sdk` and `marc272/crc-docs`, under the same conditions. **The orchestrator**, and never a worker, squash-merges a PR with `gh pr merge <n> --squash` (in a fork, see "Fork PRs" below) when all of the following hold:

- the orchestrator reviewed it against the checklist in "The loop", step 5;
- every CI check is green: none failing, none pending (in crc-docs, the fork's own checks, see "Fork PRs");
- it belongs to a non-Human, non-Gate issue, or Marc approved it on the issue or PR;
- it changes no spec decision (SPEC §11, ADR outcomes) unless Marc's answer is recorded on the Decision issue;
- it doesn't merge into, or past, a gate that isn't Done (e.g. no F5 method change before MAR-18);
- it doesn't belong to a paused project (Foundation, Website & Blog, Paper), unless it fixes a red `main`.

Otherwise, set the issue to In Review, assign it to Marc, and alert him. Never use `--admin`, never force-push, and never push to `main` (ours or a fork's) or to a fork's `parametric` directly. Nothing is ever merged upstream by an agent. Branch protection (MAR-78) may require status checks, but must **not** require approving reviews: that would block every agent merge.

### Fork PRs

The merge gate differs by fork (crc-sdk checked 2026-11-05, crc-docs 2026-11-08):

- **crc-sdk:** `.github/workflows/ci.yml` runs on every `pull_request`, with no branch filter: ruff and strict mypy, the tests on Python 3.11 to 3.14 and on Windows, and a wheel build. PRs into `parametric` get it, and it is the merge gate.
- **crc-docs:** Actions are off on `marc272/crc-docs` (Marc, 2026-11-08, because the new `live` job in upstream's `ci.yml` would reach RiskThinking's data on every PR; `gh api repos/marc272/crc-docs/actions/permissions --jq .enabled` prints `false`). No workflow runs on a PR, so the gate is local, as in "Fallback: local CI" below: the worker pastes the summary of the fork's own checks on the final head, and you re-run them in the PR's worktree, on the head you are about to merge. The checks are `uv sync --locked`, `uv run pytest -q`, `uv run ruff check pipelines tests tools` and `uv run ruff format --check pipelines tests tools`. Merge only if your run passes.
  - **`uv sync --locked`, on purpose.** Upstream's `AGENTS.md` lists `uv sync --locked --extra velo`, while its `ci.yml` and the run on crc-docs#2 use `uv sync --locked`. The `velo` extra adds only `velo-sdk`, which only the tests that need a CDT API key import, and agents never run those.
  - **Actions must stay off.** `ci.yml` runs on a weekly `schedule` and on `push` to `main` as well as on `pull_request`, so re-enabling Actions would run the `live` job.
  - **Agents never set `CRC_DOCS_LIVE=1`,** although upstream's `AGENTS.md` lists that run. It runs all of `tests/test_live.py`, and this rule has no exception, MAR-299 included. So `uv run pytest -q` skips the tests in `tests/test_live.py`, which need `CRC_DOCS_LIVE=1` or a CDT API key. Those skips are expected.
  - **The one exception so far to "never connect to RiskThinking's services"** is MAR-299 (Marc, 2026-11-08): agents may download the public CRC Open release for the primer notebook, with no credentials and only for that notebook.
  - **The skills check, by hand.** When a PR changes a path that `validate-skills.yml` watches (`.agents/skills/**`, `.claude/skills`, `.mcp.json`, `AGENTS.md`, `CLAUDE.md` or the workflow itself), run that workflow's steps on the final head as part of the gate: `.claude/skills` is a symlink to `../.agents/skills`, `CLAUDE.md` is the single line `@AGENTS.md`, `uv run python -m json.tool .mcp.json` succeeds, `.agents/skills/` holds at least one skill, and every skill there passes `uvx --from "skills-ref==0.1.1" agentskills validate <skill>` and is named in `AGENTS.md`; a sync PR is exempt when those paths at its head are identical to `upstream/main` (`git -C <worktree> diff --quiet upstream/main HEAD -- <paths>` succeeds), because the steps read only those paths, so their result would be upstream's own.
- Both forks carry upstream's `rebase-dependabot.yml`, which has no job in a fork.

Merge a fork PR so that the commit on `parametric` reads like upstream's history, with no MAR ID in its subject:

```bash
gh pr merge <n> --repo marc272/<fork> --squash \
  --subject "<conventional-commit subject> (#<n>)" --body "Refs: MAR-<issue>"
```

### Keeping `parametric` current

Marc (2026-11-05): the orchestrator keeps each fork's `parametric` current by merging upstream `main` into it. Shared branches are never rebased. Do it when upstream `main` has moved, before dispatching work that needs the new upstream code, and before Marc opens an upstream PR (MAR-249):

1. `git -C <clone> fetch upstream` and `git -C <clone> fetch origin`. If `git -C <clone> merge-base --is-ancestor upstream/main origin/parametric` succeeds, `parametric` is current.
2. Make a worktree on a sync branch: `git -C <clone> worktree add --no-track -b sync/upstream-main-<YYYY-MM-DD> <worktree> origin/parametric`.
3. `git -C <worktree> merge --no-edit upstream/main`. Resolve simple conflicts in the worktree. If a resolution needs real work, file an issue for it and dispatch it like any other.
4. Run the fork's checks (`AGENTS.md`, "Their rules are binding") in the worktree, push the sync branch, and open a PR into `parametric` (`gh pr create --repo marc272/<fork> --base parametric --head sync/upstream-main-<YYYY-MM-DD> --title "chore: merge upstream main into parametric"`).
5. When the gate passes, merge it with a merge commit: `gh pr merge <n> --repo marc272/<fork> --merge`. Never `--squash` or `--rebase` here: either would drop upstream's history from `parametric`, and the upstream PR would then show upstream's own changes as ours. A sync PR carried by a MAR-issue branch, as crc-docs#2 was, also needs `--subject "<conventional-commit subject> (#<n>)" --body "Refs: MAR-<issue>"`: the default merge message holds the branch name and the PR title, and both have the MAR ID.

A sync PR on a `sync/…` branch has no Linear issue. List it in the next Program hub status update, like Dependabot PRs.

### Dependabot PRs

Dependabot ([`.github/dependabot.yml`](../.github/dependabot.yml), MAR-77, MAR-147) opens PRs every Monday: commit prefix `ci` for GitHub Actions and pre-commit hooks, `deps` for `uv.lock`. They have no Linear issue, and their bodies don't follow the agent PR template. Handle them as follows:

- **Review the diff.** It may touch only `uv.lock`, `.github/workflows/*` or `.pre-commit-config.yaml`. Merge it with `gh pr merge <n> --squash` when every check is green, as for an agent PR.
- **A `deps` PR that touches a `pyproject.toml` is refused.** The uv entry is `lockfile-only`, so such a PR shouldn't exist. Close it with a comment saying why. A change to a requirement or floor is an issue of its own, and comes with `pixi lock` in `packages/climada`.
- **A bump that turns a job red on its merits isn't fixed on the bot's branch.** Close the PR, or leave it open, and file an issue for the incompatibility. A check that is red for an unrelated reason (a flaky job, an outage) is re-run, not treated as a failed bump.
- **No Linear issue per Dependabot PR.** List the ones merged, closed or left open in the next Program hub status update.

### Fallback: local CI while Actions minutes are exhausted

This is a fallback, not the current state. The repository is public since 2026-10-27 evening, and the GitHub checks are the merge gate again (MAR-80). Use this section only when GitHub Actions can't run for billing reasons again, as happened while the repository was private (2026-10-27, Marc, MAR-80 comment). Then [`scripts/ci_local.sh`](../scripts/ci_local.sh) is the merge gate, and it replaces "every CI check is green" above:

- **Local CI on the PR head replaces the GitHub checks.** `scripts/ci_local.sh <checkout> [job ...]` runs the jobs of `ci.yml` and `climada.yml` (lint, workspace-3.12, workspace-3.13, core-3.11-highest, core-3.11-lowest-direct, build, climada), prints a PASS/FAIL line per job and a summary with the commit, keeps its logs in a temp directory outside the checkout, and exits non-zero on any failure. It also says when the tree is dirty, which doesn't count as a run of the PR head.
- **The worker** runs every job on the final PR head and pastes the summary into the PR body under a heading "Local CI (GitHub Actions minutes exhausted)".
- **The orchestrator re-runs it before merging**, in the PR's worktree, on the head it is about to merge: at least `lint` plus the test jobs of the packages the diff touches (`workspace-3.12` and `workspace-3.13` for `core`, `viz`, `crc` or `parity`; also the `core-3.11-*` jobs and `climada` for `core`; `climada` for `packages/climada`; `build` for any `pyproject.toml` or packaging change). Run all jobs when in doubt. Merge only if that run passes.
- **Checks that are red only for billing reasons are ignored.** They fail within seconds with no steps run, and their annotation reads "The job was not started because recent account payments have failed or your spending limit needs to be increased" (`gh api repos/marc272/parametric-insurance-design/check-runs/<job id>/annotations`). A check that ran and failed on its merits still blocks.
- **The Python 3.11 gap is noted on every PR.** The `core-3.11-*` jobs need a clean Python 3.11. uv can't download Pythons on the owner's machine, so `scripts/ci_local.sh --setup` makes one with pixi from `scripts/ci_local/py311/pixi.toml` (osx-arm64 and linux-64); `CI_LOCAL_PY311=<path>` overrides it. There is one such env, in the main checkout: `--setup` builds it there even when run from a worktree, and runs from agent worktrees reuse it (MAR-150, MAR-157). When the script finds no env, its output starts with a loud warning that lists the paths it looked in. Without either, the jobs fall back to Python 3.12 and the summary warns about it. On that fallback `core-3.11-lowest-direct` can't install at all (pandas 2.1.0 has no cp312 wheel), so it fails for that reason alone. Each PR states which Python the `core-3.11-*` jobs used (the summary shows it), and that the run was on macOS rather than CI's Ubuntu.
- **The site job isn't in `ci_local.sh`.** To build the site locally (MAR-201), install the Quarto CLI pinned in `.github/workflows/site.yml` (`QUARTO_VERSION`) without a system install: download its release tarball into the ignored `results/` with `gh release download v<version> -R quarto-dev/quarto-cli -p 'quarto-<version>-macos.tar.gz' -p 'quarto-<version>-checksums.txt'`, check it with `shasum -a 256 -c --ignore-missing quarto-<version>-checksums.txt`, unpack it there, and run `results/quarto-<version>/bin/quarto render site` ([`site/README.md`](../site/README.md)).

When Actions runs again, return to the GitHub checks, and say so in the next Program hub status update.

## Resuming after an interruption

Usage limits, crashes and closed laptops are normal. At session start, after reconciling:

1. **Live worker** in this session, i.e. its agent ID still answers: `SendMessage` it to continue.
2. **Worker gone, work pushed** (a branch or draft PR exists): dispatch a new worker with the resume brief on the same branch. Post a new dispatch record.
3. **Worker gone, nothing pushed:** comment, move the issue back to Todo and re-dispatch it normally. A local worktree with uncommitted changes is reported in the comment, not deleted.
4. **PR waiting on review or CI:** carry on with review and merge.

Then continue the loop. Don't redo work that is already merged or pushed.

## Owner alerts

Marc is not watching the session. A **hard block** is anything that stops the critical path, or every free lane, until Marc acts:

- a decision or gate sign-off;
- a credential, account or repository setting;
- a contradiction between the spec and an issue;
- a worker escalation after two failed review rounds.

For each new hard block:

1. Assign the issue to Marc Prinzing and comment `@Marc Prinzing` with one concrete question, the options you see, and your recommendation. Linear then notifies him.
2. Add it to the Human queue in the next Program hub status update, with health `atRisk` if it blocks the critical path.
3. Send a one-line push notification (`PushNotification`) that leads with the action needed. Send one per new block, never for routine progress. When the session goes idle with items still waiting on Marc, send one summary notification.

Keep the other lanes moving while you wait.

Work started before the repository existed went into the workspace folder `/Users/marcprinzing/Parametric_Insurance/repo-seed/` at its target path, and the bootstrap (MAR-6) copied it in. New work goes straight into this repository, on its issue branch.

## The human queue

Keep one running list of what needs Marc: Human issues in Todo or In Review, worker escalations, and decisions on the critical path. Ask in batches, keep the other lanes moving while you wait, and put the list in every Program hub status update. Record answers on the relevant issue before acting on them.

## Gates

- **MAR-18, parity.** When MAR-67 to MAR-70 are Done:
  - assemble `parity/REPORT.md` (summary plus every explained gap);
  - set MAR-18 to In Review and ask the human to sign off.

  No method change (F5, Paper) is dispatched before MAR-18 is Done.
- **MAR-29, checkpoint C1.** When the core v1 features (MAR-22 to MAR-27) are Done:
  - dispatch the prep (the `research/checkpoints/C1.md` draft);
  - set it to In Review for the human's decisions on the narrative, D4 and D6;
  - afterwards, cancel MAR-35 if D6 = no, and update the publication rule on the Program hub to the claims C1 allows.

## The plan (2026-11-05)

The CRC plan, in milestone order (SPEC §8; the CRC Contribution project in Linear):

1. **R1, setup and module design:** MAR-242 R-10 the forks (Human) · MAR-243 R-11 the program rules · MAR-244 R-12 ADR 0005 (D10, Marc approves) · MAR-245 R-13 golden fixtures from the core. All but R-10 run in this repository.
2. **R2, the Phase 1 module in crc-sdk:** MAR-246 R-14 covers and payout functions → MAR-43 R-15 outcome samples → MAR-247 R-17 evaluation and comparison → MAR-248 R-16 design → MAR-42 R-18 end-to-end workflow and docs.
3. **R3, the notebook and the upstream PRs:** MAR-46 R-19 the notebook in crc-docs → MAR-249 R-20 the contribution route and the upstream PRs (Human).
4. **R4, the Phase 2 extensions:** MAR-45 R-21 portfolio approach · MAR-250 R-22 multi-hazard covers · MAR-44 R-23 scenario analysis · MAR-41 VELO assets.

Everything in the forks waits on MAR-242 (the forks) and MAR-244 (Marc's approval of ADR 0005). The CLIMADA prototype (MAR-168) takes a slot when CRC has no ready agent work. The Foundation start sequence of 2026-10-25 (bootstrap, contract, core lanes, parity, core v1 features) is done; its record is in Linear and git.

## Reference material (absolute paths on the owner's machine)

- Workspace guide: `/Users/marcprinzing/Parametric_Insurance/CLAUDE.md`.
- Thesis code (parity source, read-only): `/Users/marcprinzing/Parametric_Insurance/parametric-insurance-framework`.
- Fork clones (R-10): `/Users/marcprinzing/Parametric_Insurance/forks/crc-sdk` and `/Users/marcprinzing/Parametric_Insurance/forks/crc-docs`. Never edit their own checkouts: fork work happens in worktrees under `/Users/marcprinzing/Parametric_Insurance/forks/worktrees/` ("Worker worktrees in the forks").

## You never

- Do anything on the "Never" list in `AGENTS.md`. In particular, never act on RiskThinking's repositories or contact RiskThinking: the upstream PRs and every contact are Marc's (MAR-249).
- Start a session anywhere but here. Call `start_session` only without `cwd`, `host`, `preset`, `environment` or `repository`, and with no `target` other than `"local"`: then it runs in this repository and loads its deny rules and hooks. A session started elsewhere runs without them, so the session guard refuses those fields (MAR-289). Workers you brief follow the same rule (Marc, 2026-11-06, MAR-282).
- Sign in to GitHub in the Browser pane. Its sign-ins persist, and a pane signed in there could merge, release or change settings outside every `gh` rule. No hook checks this: the rule is the control (Marc, 2026-11-08, MAR-282).
- Rerun a run of this repository other than a failed CI run of an open PR (`gh run rerun <id> --failed`). A rerun of a Site run on `main` deploys that commit's site again, and no offline check can tell a Site run's ID from a CI run's (MAR-289).
- Create, change or run scheduled tasks (the `scheduled-tasks` tools) or cloud routines (`/schedule`). Each starts a session later, in its own folder and permission mode, outside this loop. Scheduling is Marc's. `/loop` and its wakeups in this session are fine (Marc, 2026-11-06, MAR-282).
- Dispatch or merge work from a paused project, except a fix for a red `main`.
- Mark a Human or Gate issue Done yourself, unless the owner explicitly delegates that decision in the conversation.
- Change spec decisions without the human's recorded answer.
- Restructure Linear projects or milestones without asking. Creating issues and sub-issues, and editing descriptions to match reality, are part of your job.
