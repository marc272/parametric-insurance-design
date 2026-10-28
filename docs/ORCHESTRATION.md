# Orchestrator runbook

You coordinate the **parametric-insurance-design** program. You plan, delegate issues to worker subagents, review, merge, and **keep Linear true**. You never do Human work. Workers follow [`AGENTS.md`](../AGENTS.md). The owner is Marc Prinzing.

## Operating model

- **Autonomous.** Marc starts an orchestrator session by hand, in auto mode, with `/orchestrate` (or `/loop /orchestrate` to keep it waking up while it waits on him). From then on the orchestrator runs the loop below on its own: it dispatches, reviews, merges and keeps Linear current. It contacts Marc only for hard blocks and Human work (see "Owner alerts").
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
       "Source control: github.com/marc272 (the owner's own GitHub account). marc272/parametric-insurance-design is a public repository the owner created for this work",
       "Key services: the owner's Linear workspace 'Marc prinzing' (team MAR), reached through the Linear connector, is the program's tracker. Agents create and update issues, comments and project status updates there as part of the documented workflow (docs/ORCHESTRATION.md)"
     ],
     "allow": [
       "$defaults",
       "Agent PR merges in marc272/parametric-insurance-design: on 2026-10-25 the owner, Marc Prinzing, authorised the orchestrator agent to squash-merge PRs (`gh pr merge <n> --squash`) without a human approval, after it has reviewed the PR and all CI checks are green (see the repository's CLAUDE.md and docs/ORCHESTRATION.md 'Merge policy'). This does not cover admin merges, force pushes, direct pushes to main, or a worker merging its own PR"
     ]
   }
   ```

   While Actions minutes are exhausted, "all CI checks are green" in this text is met by the local-CI fallback (see "Merge policy", "Fallback: local CI while Actions minutes are exhausted"). The block itself doesn't need to change.

2. **Start sessions in auto mode.** Otherwise every command prompts and the loop stalls.
3. **Optional: phone alerts.** Connect Remote Control, so that `PushNotification` reaches your phone as well as the desktop.
4. **Guardrails, already checked in.** `.claude/settings.json` denies force pushes, pushes to `main`, admin merges and repository edits or deletes, in every mode.

## Ground truth

- **Linear** (workspace "Marc prinzing", team MAR) is the source of truth for what we aim to do, priorities, plan, decisions and status. The entry point is the [Program hub](https://linear.app/marc-prinzing/project/program-hub-1b757250497c): its description (mission, outputs, phases, scheduling and publication rules, decision index) and its status updates (where we are).
- `docs/SPEC.md` is the source of truth for the *how*. ADRs record technical decisions.
- If reality, a file and Linear disagree, find out what is true, then fix Linear (or the file) in the same session. **Keeping Linear current is part of your job, not an afterthought.**

## Session start

1. Read the Program hub description and its latest status update.
2. List the team's issues that are **In Progress** and **In Review**. Reconcile each with git and PR state:
   - is a PR merged without the issue being Done?
   - is a worker gone while its issue is still In Progress?

   Fix Linear first. Resume or re-dispatch interrupted work as described in "Resuming after an interruption".
3. Read new comments since the last status update, especially on Human issues: the owner may have answered.
4. Rebuild the ready set (see "The loop") and decide this session's dispatches.

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
- **Decision:** one of D1–D7. Always also Human. The outcome is recorded on the issue, and technical outcomes also get an ADR.
- **Spike, Research, Feature, Chore:** informational.

**Containers.** An issue with sub-issues (MAR-17, MAR-18, MAR-19) is never dispatched. Mark it Done when all its sub-issues are Done. For a Human container (MAR-18), set it to In Review with the assembled result and let the human close it.

**Scope.** Only issues in the program's projects count. Ignore issues without a project, such as Linear's onboarding issues MAR-1 to MAR-4.

**Keeping Linear true**

- Every piece of work maps to an issue. If you or a worker discover new work, file it immediately (project, milestone, blockers, acceptance) rather than carrying it in your head.
- When an issue's scope changes, edit its **description**. A comment alone is not enough, because the description is what the next worker reads.
- Decisions are recorded on their Decision issue. Then `docs/SPEC.md` §11 or an ADR is updated through a small PR before dependent work is dispatched.
- After any change to the spec or the plan, check open issues in **all** projects for impact, and update them.

## Scheduling across streams

The Program hub sets these rules:

1. **Foundation first.** Ready Foundation issues get worker slots before anything else; Foundation is the critical path.
2. **Then the nearest public release.** Prefer work that brings the next public output forward (website v1 and posts, CRC showcase, CLIMADA module). These are equally important, and they publish sooner than the paper.
3. **Keep the long track moving.** Whenever the Paper project has ready work, at least one worker slot goes to it.
4. **Raise Human issues early** when they sit on the path to a release.
5. **Publication rule:** until C1 is Done, review every external-facing deliverable for it. The method and tool only, the setup stated, numbers from out-of-sample runs on the annual basis, and no general claim that tail optimisation outperforms.

## The loop

1. **Sync.** Do the session-start steps, then move Backlog → Todo for every issue whose blockers are all Done.
2. **Pick.** Leaf issues in Todo without the Human label, ordered by the scheduling rules above, then priority, then milestone. Constraints:
   - at most **3 workers** at once (4 when the lanes are clearly independent);
   - no two concurrent issues may own the same module (ADR 0002 ownership map);
   - serialise anything that touches `pyproject.toml`, lockfiles (`uv.lock`, `packages/climada/pixi.lock`) or CI config. A change to the core's dependencies must also run `pixi lock` in `packages/climada` and commit `pixi.lock`, because the climada CI job installs with `--locked` (ADR 0002 §10, MAR-71).
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

   Request changes from the same worker, which keeps its context. After two failed rounds, escalate to the human. For core numerical code, an independent reviewer subagent is worth the cost.
6. **Merge.** Follow the "Merge policy" below: squash-merge agent PRs that pass review, in dependency order, rebasing dependents when needed. Set the issue to Done, comment with the PR link, and file the reported follow-ups.
7. **Repeat** from step 1. End the session with the session-end steps.

## Delegating to subagents

**One issue = one worker = one branch = one PR.** Each worker gets its own git worktree, on the issue's Linear branch name cut from the latest `main`. In Claude Code, either:

- spawn a subagent per issue with worktree isolation. Its report comes back to you, which is the default; or
- start a separate session per issue when the owner wants to follow that work directly.

Workers may not have the Linear connector. You stay responsible for Linear in both cases.

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

**Resume brief.** Use this when a worker is gone but its branch or draft PR exists. Put this before the normal brief:

```text
You are resuming interrupted work. Branch <name> already exists (PR #<n>, if any).
Check it out in your worktree (git fetch && git switch <name>), read its commits and the PR body,
and continue from there. Don't restart from main, and don't rewrite pushed history.
Still to do, as far as the orchestrator knows: <list>.
```

## Dispatch record

Every dispatch, re-dispatch or resume posts one comment on the issue, so that a later session can find and resume the work:

```text
Dispatch record
- worker: <agent ID or session link>, started <ISO time>
- branch: <gitBranchName>   worktree: <path, if known>
- PR: <link, or "none yet">
- notes: <resume of …, review round n, anything a successor needs>
```

Update the record with a new comment when the PR opens, and at each review round.

## Merge policy

Marc authorised agent merges on 2026-10-25 ("PR should be merged automatically in general", MAR-80). **The orchestrator**, and never a worker, squash-merges a PR with `gh pr merge <n> --squash` when all of the following hold:

- the orchestrator reviewed it against the checklist in "The loop", step 5;
- every CI check is green: none failing, none pending;
- it belongs to a non-Human, non-Gate issue, or Marc approved it on the issue or PR;
- it changes no spec decision (SPEC §11, ADR outcomes) unless Marc's answer is recorded on the Decision issue;
- it doesn't merge into, or past, a gate that isn't Done (e.g. no F5 method change before MAR-18).

Otherwise, set the issue to In Review, assign it to Marc, and alert him. Never use `--admin`, never force-push, and never push to `main` directly. Branch protection (MAR-78) may require status checks, but must **not** require approving reviews: that would block every agent merge.

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
- **The Python 3.11 gap is noted on every PR.** The `core-3.11-*` jobs need a clean Python 3.11. uv can't download Pythons on the owner's machine, so `scripts/ci_local.sh --setup` makes one with pixi from `scripts/ci_local/py311/pixi.toml` (osx-arm64 and linux-64); `CI_LOCAL_PY311=<path>` overrides it. Without either, the jobs fall back to Python 3.12 and the summary warns about it. On that fallback `core-3.11-lowest-direct` can't install at all (pandas 2.1.0 has no cp312 wheel), so it fails for that reason alone. Each PR states which Python the `core-3.11-*` jobs used (the summary shows it), and that the run was on macOS rather than CI's Ubuntu.

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

## Start sequence

1. **Bootstrap:** MAR-6. The human first creates the GitHub repo `marc272/parametric-insurance-design`. MAR-6 copies everything in `repo-seed/` and moves `SPEC.md` to `docs/`.
2. **Contract:** MAR-8 EventSet → MAR-61 interfaces and ownership map.
3. **Core lanes, in parallel:**
   - **A:** MAR-11 payout → MAR-13 objectives → MAR-14 problem builder → MAR-15 engine tests
   - **B:** MAR-12 scopes (after MAR-11) → MAR-16 evaluation
   - **C:** MAR-9 parity fixture, MAR-10 noise port
   - **D:** MAR-71 → MAR-72 → MAR-73 CLIMADA adapter
4. **Runner and parity:** MAR-63 → MAR-64 → MAR-65 → MAR-66, then MAR-67 → MAR-68 → MAR-69 / MAR-70 → **MAR-18 sign-off**.
5. **Core v1 features (F5):**
   - MAR-22 / MAR-23 out-of-sample evaluation, MAR-24 annual basis, MAR-27 loaded pricing (after MAR-18);
   - MAR-25 vulnerability draws, MAR-26 cat-in-a-circle (after the CLIMADA adapter).
6. **Early releases, in parallel:**
   - Website v1 (MAR-53 → MAR-54 / MAR-55 → MAR-58 → MAR-60);
   - CRC showcase (MAR-42 to MAR-46);
   - CLIMADA module (MAR-47 → MAR-48 → MAR-49 → MAR-50 → MAR-51).
7. **Paper track alongside:**
   - MAR-28 positioning from day one;
   - MAR-29 C1 after F5;
   - then MAR-30 to MAR-40;
   - its results feed the Website v2 (MAR-56, MAR-59, MAR-74).
8. **Any time, preparation only:** MAR-41 (CRC Open part), MAR-62 (D7 note), MAR-52 (website ADR draft), MAR-57 (post 1 draft).

## Reference material (absolute paths on the owner's machine)

- Workspace guide: `/Users/marcprinzing/Parametric_Insurance/CLAUDE.md`.
- Thesis code (parity source, read-only): `/Users/marcprinzing/Parametric_Insurance/parametric-insurance-framework`.
- CRC docs and SDK examples (read-only): `/Users/marcprinzing/Parametric_Insurance/crc-docs`.

## You never

- Do anything on the "Never" list in `AGENTS.md`.
- Mark a Human or Gate issue Done yourself, unless the owner explicitly delegates that decision in the conversation.
- Change spec decisions without the human's recorded answer.
- Restructure Linear projects or milestones without asking. Creating issues and sub-issues, and editing descriptions to match reality, are part of your job.
