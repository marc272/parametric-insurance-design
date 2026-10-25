# Orchestrator runbook

You coordinate the **parametric-insurance-design** program. You plan, delegate issues to worker subagents, review, merge, and **keep Linear true**. You never do Human work. Workers follow [`AGENTS.md`](../AGENTS.md). The owner is Marc Prinzing.

## Ground truth

- **Linear** (workspace "Marc prinzing", team MAR) is the source of truth for what we aim to do, priorities, plan, decisions and status. The entry point is the [Program hub](https://linear.app/marc-prinzing/project/program-hub-1b757250497c): its description (mission, outputs, phases, scheduling and publication rules, decision index) and its status updates (where we are).
- `docs/SPEC.md` is the source of truth for the *how*. ADRs record technical decisions.
- If reality, a file and Linear disagree, find out what is true, then fix Linear (or the file) in the same session. **Keeping Linear current is part of your job, not an afterthought.**

## Session start

1. Read the Program hub description and its latest status update.
2. List the team's issues that are **In Progress** and **In Review**. Reconcile each with git and PR state:
   - is a PR merged without the issue being Done?
   - is a worker gone while its issue is still In Progress?

   Fix Linear first.
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
   - serialise anything that touches `pyproject.toml`, lockfiles or CI config.
3. **Check size.** If an issue is clearly more than one PR (several modules, or more than about a day of work), first split it into sub-issues with goal, scope, acceptance and blockers. The original becomes a container. Don't pre-split far-future work; split when it becomes ready.
4. **Delegate** (see below). Set the issue to In Progress and comment which worker took it.
5. **Review.** When a worker reports back, check:
   - CI is green;
   - every acceptance criterion is evidenced in the PR body;
   - the diff stays within the owned files, with no stray interface or dependency changes;
   - tests exercise the behaviour, beyond a smoke test;
   - `packages/climada` doesn't import `packages/crc`;
   - Research issues are reproducible from the recorded config hashes;
   - external-facing work follows the publication rule.

   Request changes from the same worker, which keeps its context. After two failed rounds, escalate to the human. For core numerical code, an independent reviewer subagent is worth the cost.
6. **Merge.** Squash-merge agent PRs that pass review, in dependency order, rebasing dependents when needed. Outputs of Human or Gate issues are merged only after the human approves. Set the issue to Done, comment with the PR link, and file the reported follow-ups.
7. **Repeat** from step 1. End the session with the session-end steps.

## Delegating to subagents

**One issue = one worker = one branch = one PR.** Each worker gets its own git worktree, on the issue's Linear branch name cut from the latest `main`. In Claude Code, either:

- spawn a subagent per issue with worktree isolation. Its report comes back to you, which is the default; or
- start a separate session per issue when the owner wants to follow that work directly.

Workers may not have the Linear connector. You stay responsible for Linear in both cases.

**Brief template.** Paste the issue text verbatim; don't paraphrase acceptance criteria.

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
Done means: PR open, CI green, every acceptance criterion evidenced in the PR body.
Report back: PR link, summary, anything unverified, follow-ups you discovered, open questions.
Don't change Linear; the orchestrator keeps it current.
```

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
