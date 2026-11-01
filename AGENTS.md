# Working agreement for agents

This repository is built by several worker agents coordinated by an orchestrator agent. The human owner is Marc Prinzing. This file is **binding for every worker**. The orchestrator follows [`docs/ORCHESTRATION.md`](docs/ORCHESTRATION.md).

## The program in brief

- **Goal:** turn a master's thesis on parametric insurance into public outputs. The thesis had two ideas: tail-risk–optimised payout design (a weighted CVaR objective, solved as an LP) and portfolio-level calibration (payouts calibrated jointly across assets: individual, cluster and portfolio scopes).
- **Two co-equal stories, and their combination.** Each idea is a core story of the program and must stand on its own, not only in combination:
  - **RQ1, tail:** when does a tail-optimised (weighted-CVaR) design pay against MSE and E[U] designs?
  - **RQ2, portfolio:** when does joint calibration (portfolio or cluster scope) pay against calibrating each asset on its own, under each objective (MSE, E[U], weighted CVaR)? The use case is one risk owner with many sites, who cares about the total shortfall, so sites can cover each other.
  - **Combination (RQ1 × RQ2):** a weighted-CVaR objective calibrated jointly across one owner's sites. The two ideas can be studied in isolation and in combination, depending on the use case: one site calls for the tail view; many sites with an average-fit mandate, the portfolio view; many sites with a tail mandate, the combination.

  C1, the paper, the posts and the outputs report both stories and their combination, each with its own evidence.
- **Outputs, equally important:**
  - a website with explorers, plus blog/LinkedIn posts;
  - a showcase on Climate Risk Commons data;
  - a module contributed to CLIMADA;
  - a peer-reviewed paper.
- **One shared core:** everything builds on this repository's core library, `parametric_insurance_design`. Foundation work is the critical path.
- **Early vs. long track:** the website, posts, CRC showcase and CLIMADA module are early releases that ship once the core v1 features exist. The paper is the long track, and its results feed later updates.
- **Publication rule** (decided at C1, 2026-11-01; MAR-29). Every external output (website, posts, READMEs, docs pages, the CLIMADA module's text):
  - presents the method and the tool;
  - states the setup of every number shown: portfolio, basis, basis-risk model, pricing and split;
  - uses numbers from out-of-sample runs on the annual basis;
  - RQ1 (tail): makes only conditional, mechanism-based statements tied to a stated setup (e.g. "on the thesis portfolio, under pure pricing, …"). No general claim that tail optimisation outperforms;
  - RQ2 (joint calibration): method only, meaning what joint calibration is and what it optimises. No comparative claim, in either direction;
  - the combination: any statement involving joint calibration follows the RQ2 rule;
  - links no private Linear pages.

  The owner revisits the RQ2 rule after the Florida rerun (MAR-152 item 4).
- **Hard boundaries:**
  - `core` and `viz` never import an adapter;
  - the CLIMADA stream never touches CRC/VELO code or data;
  - every package keeps its licence (ADR 0001).

  CI enforces the import rules (MAR-76): `parametric_insurance_design` (core) and `parametric_insurance_design_viz` never import `parametric_insurance_design_crc` or `parametric_insurance_design_climada`; `parametric_insurance_design_climada` never imports `parametric_insurance_design_crc`; core never imports viz, except the lazy `importlib` call in `cli.py`'s `figures` command (MAR-110). The bans are ruff `TID251` (banned-api) in the `[tool.ruff]` table of `packages/core`, `packages/viz` and `packages/climada/pyproject.toml`, applied by `ruff check` in the `lint` job to src, tests and scripts. `scripts/check_import_boundaries.sh`, in the same job, proves they fire.
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
- **Push early.** Push the branch after your first commit, open a **draft** PR, and push after every meaningful commit. Sessions can be interrupted at any time, for example by usage limits, and only pushed work can be resumed. Mark the PR ready when you report back.
- If your brief says you are resuming, continue on the existing branch. Don't restart from `main`, and don't rewrite pushed history.
- Never push to `main`, never merge any PR (merging is the orchestrator's job), and never force-push a branch someone else uses.

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

- CI is green on the PR, or, while Actions minutes are exhausted, `scripts/ci_local.sh` passes on the PR head and its summary is in the PR body (under "Local CI (GitHub Actions minutes exhausted)"; runbook "Merge policy").
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
