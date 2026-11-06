---
name: orchestrate
description: Run (or resume) the parametric-insurance-design orchestrator. Reconciles Linear with git and PRs, dispatches ready issues to worker subagents, reviews and merges their PRs, keeps Linear true, and alerts Marc on hard blocks. Safe to re-run at any time, including after a usage-limit reset.
---

# /orchestrate

You are the **orchestrator** of the parametric-insurance-design program. [`docs/ORCHESTRATION.md`](../../../docs/ORCHESTRATION.md) is your binding runbook, and this skill is how you run it. Run it in **auto mode** so the loop doesn't stall on permission prompts.

All state lives in Linear, git and GitHub, never in this conversation, so this skill is **idempotent**: running it again, in this session or a new one, picks up exactly where the last run stopped.

## 0. Preconditions (stop and alert Marc if any fails)

- The Linear connector works: you can read the [Program hub](https://linear.app/marc-prinzing/project/program-hub-1b757250497c).
- `gh auth status` succeeds, and `git fetch` works in `/Users/marcprinzing/Parametric_Insurance/parametric-insurance-design`.
- The main checkout is on `main` with a clean tree. Never do worker edits in it: workers get their own worktrees.
- The session runs in this repository, with `/Users/marcprinzing/Parametric_Insurance/forks` added as a working directory (runbook "One-time setup", step 2). Started elsewhere, it lacks this repository's deny rules.

**Fork preconditions.** If one fails, stop fork work only and alert Marc; the other lanes go on. For each fork clone, `/Users/marcprinzing/Parametric_Insurance/forks/crc-sdk` and `/Users/marcprinzing/Parametric_Insurance/forks/crc-docs`:

- `git -C <clone> fetch origin` and `git -C <clone> fetch upstream` work;
- `git -C <clone> remote get-url --push upstream` prints `DISABLED`;
- `gh repo set-default --view`, run in the clone, prints `marc272/<fork>`.

## 1. Session start (runbook "Session start", plus resume)

1. Read the Program hub description and its **latest status update**.
2. `git fetch --prune`, then `git switch main && git pull --ff-only`.
3. Collect the facts, for each of the three repositories. `<repo>` is `marc272/parametric-insurance-design`, `marc272/crc-sdk` or `marc272/crc-docs`; always pass `--repo`:
   - `gh pr list --repo <repo> --state open --json number,title,headRefName,baseRefName,isDraft,statusCheckRollup`;
   - `gh pr list --repo <repo> --state merged --limit 20 --json number,headRefName,mergedAt`;
   - `git worktree list` here, and `git -C <clone> worktree list` in each fork clone;
   - Linear issues of team MAR that are **In Progress** or **In Review**.
4. **Reconcile** each In Progress or In Review issue, using its latest *Dispatch record* comment (runbook "Dispatch record"):

   | What you find | What you do |
   |---|---|
   | PR merged, issue not Done | Set it Done. Comment with the PR link. File the follow-ups |
   | PR open, CI green, review not done | Review it now (step 3 below) |
   | PR open, CI red or changes needed | Resume the worker (below) with the failures |
   | Branch or draft PR with work, no PR ready | Resume the worker (below) |
   | Nothing pushed, no live worker | Move the issue back to Todo, with a comment, and re-dispatch it in the loop |
   | Human issue In Review | Leave it. Check for new comments from Marc |

   **Resuming a worker.** First try `SendMessage` to the agent ID in the dispatch record ("continue: <what is left>"). This only works if the agent still exists in this session. Otherwise, dispatch a **new** worker on the **existing branch**, with the resume brief from the runbook, and post a new dispatch record.
5. Read comments on Human, Gate and Decision issues since the last status update. Marc may have answered. Record each answer on its issue, then act on it.
6. Clean up: `git worktree remove` (in a fork, `git -C <clone> worktree remove`) the worktrees whose PR is merged and that have no uncommitted changes. Never delete branches or data.
7. **Keep `parametric` current.** In each fork, if upstream `main` has moved past `parametric`, merge it in through a sync PR (runbook "Keeping `parametric` current"). Never rebase `parametric`.

## 2. The loop (runbook "The loop")

Repeat until no step can make progress:

1. **Sync.** Move Backlog → Todo for every issue whose blockers are all Done.
2. **Pick** ready leaf issues without the Human label, following the scheduling rules (runbook "Scheduling across streams"):
   - CRC Contribution first, in milestone order R1 → R2 → R3 → R4;
   - CLIMADA Contribution only when CRC has no ready agent work;
   - nothing from the paused projects (Foundation, Website & Blog, Paper), even in Todo, until Marc resumes one. Their open PRs get no rebases and no merges. Fixing a red `main` is still allowed.

   Respect the limits: at most 3 workers across the three repositories, no two on the same module, and anything touching a `pyproject.toml`, `uv.lock`, `pixi.*` or `.github/` runs one at a time in its repository.
3. **Split** issues that are too big into sub-issues before dispatching them.
4. **Dispatch** each pick:
   - **in this repository:** spawn a worker with `Agent`, `isolation: "worktree"`, `run_in_background: true`, using the runbook brief template;
   - **in a fork:** `isolation: "worktree"` only makes worktrees of this repository, so make the worktree yourself (runbook "Worker worktrees in the forks"):

     ```bash
     git -C <clone> fetch origin
     git -C <clone> worktree add --no-track -b <gitBranchName> \
       /Users/marcprinzing/Parametric_Insurance/forks/worktrees/<fork>-mar-<n> origin/parametric
     ```

     Then spawn the worker with `Agent`, `run_in_background: true` and **no** `isolation`, using the runbook's fork brief template with that path;
   - set the issue to **In Progress**;
   - post a **Dispatch record** comment on it, with the repository and the worktree path.

   Then keep working on other steps. You are notified when a worker finishes; don't poll.
5. **Review** each PR a worker reports, against the runbook checklist, with the fork checks for a fork PR. Wait for CI with `gh pr checks <n> --repo <repo> --watch` (in the background if it's slow). In crc-docs, whose CI doesn't run the tests, re-run the fork's checks (`uv run --with pytest python -m pytest -q`) in the PR's worktree, on the head you are about to merge. While the known upstream failure stands, run them on the base too: the gate is no new failures against the base (runbook "Fork PRs"). While Actions minutes are exhausted, follow the runbook's "Fallback: local CI": check the worker's pasted `scripts/ci_local.sh` summary and re-run the relevant jobs in the PR's worktree before merging. If the review fails, send the findings to the same worker. After two failed rounds, escalate to Marc.
6. **Merge** the PRs that pass review, in dependency order (runbook "Merge policy"):
   - in this repository: `gh pr merge <n> --repo marc272/parametric-insurance-design --squash`, then `git pull --ff-only` on `main`;
   - in a fork: `gh pr merge <n> --repo marc272/<fork> --squash --subject "<conventional-commit subject> (#<n>)" --body "Refs: MAR-<issue>"`, then `git -C <clone> fetch origin`;
   - set the issue to Done, comment with the PR link, and file the reported follow-ups.

   Update dependent branches if needed; never rebase `main` or `parametric`. **Never merge** a Human or Gate output, a PR with red or pending CI (except billing-only red, per the runbook's "Fallback: local CI"), a PR that changes a spec decision without Marc's recorded answer, or a PR of a paused project (except a fix for a red `main`). Never merge anything upstream: the upstream PRs are Marc's (MAR-249).
7. **Prepare** "Agent may prepare" parts of Human issues when a worker slot is free and nothing on the critical path is ready. Then set the issue to In Review, assign it to Marc, and alert him (step 3).

While workers run, stay responsive. End your turn only when you're waiting on workers, because their completion wakes you.

## 3. Alerting Marc (runbook "Owner alerts")

A **hard block** means the critical path, or every free lane, can't move without Marc. Examples: a decision, a sign-off, a credential or account, a repository setting, a contradiction between the spec and an issue, or a worker escalation after two failed rounds. When one comes up:

1. On the issue: assign it to **Marc Prinzing** and comment `@Marc Prinzing` with one concrete question, the options you see, and your recommendation.
2. Add it to the **Human queue** in the next Program hub status update. Use health `atRisk` if it blocks the critical path.
3. Call `PushNotification` with one line that leads with the action, e.g. `MAR-18 parity report ready: sign-off needed to unblock F5`. Send one notification per new hard block, never for routine progress.

Then keep the other lanes moving. Don't stop the loop for a block that only affects one lane.

## 4. Stopping (runbook "Session end")

Stop the loop when no worker is running and nothing is dispatchable or mergeable: everything left is Backlog, Human, paused, or blocked on Marc. Also stop before a long pause. Then:

1. Leave Linear true, following the runbook "Session end" list. No In Progress issue may be left without a live worker or a dispatch record you can resume.
2. Post a Program hub status update in the runbook's format.
3. If Marc is needed, send **one** `PushNotification` that sums up the Human queue, e.g. `Orchestrator idle: 3 items need you (MAR-18 sign-off, MAR-52 D5, MAR-79 licence)`.

If you run under `/loop` and are waiting only on Marc, schedule the next wakeup 30–60 minutes out. On each wakeup, re-run this skill from step 1, which picks up his answers.

## After a usage-limit interruption

Nothing is lost:

- workers push early, and their branches and draft PRs persist;
- every dispatch is recorded on its issue.

After the reset, Marc types `continue` in this session, or `/orchestrate` in a new one. Either way, start again at step 1. The reconciliation table resumes or re-dispatches every interrupted worker.
