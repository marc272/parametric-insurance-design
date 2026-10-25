# Working agreement for agents

This repository is built by several worker agents coordinated by an orchestrator agent. The human owner is Marc Prinzing. This file is **binding for every worker**. The orchestrator follows [`docs/ORCHESTRATION.md`](docs/ORCHESTRATION.md).

## The program in brief

- **Goal:** turn a master's thesis on parametric insurance into public outputs. The thesis ideas are tail-risk–optimised payout design (a weighted CVaR objective, solved as an LP) and portfolio-level calibration across assets.
- **Outputs, equally important:**
  - a website with explorers, plus blog/LinkedIn posts;
  - a showcase on Climate Risk Commons data;
  - a module contributed to CLIMADA;
  - a peer-reviewed paper.
- **One shared core:** everything builds on this repository's core library, `parametric_insurance_design`. Foundation work is the critical path.
- **Early vs. long track:** the website, posts, CRC showcase and CLIMADA module are early releases that ship once the core v1 features exist. The paper is the long track, and its results feed later updates.
- **Publication rule:** until checkpoint C1 (MAR-29) is Done, anything public presents the method and the tool, states the setup of every number, and makes no general claim that tail optimisation outperforms.
- **Hard boundaries:**
  - `core` and `viz` never import an adapter;
  - the CLIMADA stream never touches CRC/VELO code or data;
  - every package keeps its licence (ADR 0001).
- **Current plan and status:** in Linear, at the [Program hub](https://linear.app/marc-prinzing/project/program-hub-1b757250497c). Your issue says why your piece matters. If it doesn't, ask.

## Sources of truth, in order

1. **Linear** (team MAR): what we aim to do, priorities, plan, decisions and status. For you, that means the issue you were given: its goal, scope and acceptance criteria.
2. [`docs/SPEC.md`](docs/SPEC.md): the *how* (method, architecture, data contract, standards). Binding.
3. ADRs in `docs/adr/`. ADR 0002 defines the core interfaces and the **module ownership map**.

If these conflict, stop and escalate. Never resolve a conflict by editing the spec, an ADR or Linear yourself.

## Before you start

- Read your issue, the spec sections it cites, and ADR 0002.
- Confirm that every "blocked by" issue is Done and its PR is merged. If not, stop and report back.
- Linear status changes belong to the orchestrator. You report back to it; if you have Linear access, you may only comment on your own issue.

## Scope discipline

- **One issue = one branch = one PR.** Do only the issue you were given.
- Edit only the files your issue owns (ADR 0002 ownership map), plus new tests and docs for them. You may import other modules but must not edit them. If you need an interface change, stop and escalate.
- No drive-by refactors, formatting churn or unrelated cleanups. A new third-party dependency needs a one-line justification in the PR body.

## Branch, commits, PR

- Branch: the issue's Linear branch name (e.g. `marcprinzing/mar-11-f-03-steppayout-and-basis-matrix-builder`), cut from the latest `main`.
- Commits: small, imperative, prefixed with the issue ID, e.g. `MAR-11: add StepPayout basis matrix`.
- PR title: `[MAR-11] <issue title>`. The PR body contains:
  - a link to the Linear issue;
  - the acceptance criteria as a checklist, each ticked with evidence (test name, command output or file);
  - deviations from the issue, and why;
  - follow-ups you noticed, proposed rather than done.
- Never push to `main`, never merge your own PR, and never force-push a branch someone else uses.

## Engineering standards (SPEC §4.3)

- Core supports Python 3.11–3.13. Type hints everywhere. Numpy-style docstrings.
- ruff (lint and format) and pyright (basic) clean. pytest with meaningful tests. Core coverage ≥ 85 %.
- Determinism: pass `np.random.Generator` objects explicitly. No global seeds.
- **No silent failures:** raise typed errors or record failures explicitly. Never `except: pass`, and never drop rows, entities or runs quietly.
- No library logic in notebooks.
- Never commit data beyond small fixtures. Downloads go through scripts with checksums.
- Environments:
  - uv workspace: `core`, `viz`, `crc`.
  - pixi: `packages/climada`.
  - Never add CLIMADA to the uv workspace or CRC to the pixi env.
  - `packages/climada` must never import `packages/crc`. The CLIMADA stream is CRC-free.

## Definition of done

- CI is green on the PR.
- Every acceptance criterion is met and evidenced in the PR body.
- Tests cover the new behaviour. Docstrings and docs are updated.
- No new TODOs without a proposed follow-up.

Then report back to the orchestrator:
- the PR link and a short summary;
- anything you could not verify;
- **work you discovered but did not do** (follow-ups, bugs, gaps), each with a one-line rationale.

The orchestrator files the follow-ups in Linear. Nothing you learn should exist only in your session.

## Escalate instead of guessing

Stop and report to the orchestrator, with a concrete question and the options you see, when:

- acceptance criteria are ambiguous or contradict the spec;
- you need an interface change, a significant new dependency, or a decision listed in SPEC §11;
- a parity or research result looks wrong and you can't explain it;
- the work would need credentials, accounts or any outward-facing action.

## Never

- Use, request or store credentials, or sign in to services.
- Publish, post, submit or send anything outside this repository: discussions or PRs on other repos, arXiv, blogs, LinkedIn, emails.
- Archive, delete or rewrite the history of any repository, or delete data.
- Change Linear projects, milestones, labels or other issues. Edit decisions in the spec.
- Work on issues labelled **Human**, beyond the "Agent may prepare" part you were explicitly given.

## Research issues

- Record the config hash for every result you cite.
- Report **observations, not conclusions**. Interpretation belongs to the human (checkpoint C1, positioning, manuscript).
