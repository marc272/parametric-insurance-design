# Working agreement for agents

The program is built by several worker agents coordinated by an orchestrator agent, in this repository and in two forks of RiskThinking's repositories. The human owner is Marc Prinzing. This file is **binding for every worker**, in this repository and in the forks. The orchestrator follows [`docs/ORCHESTRATION.md`](docs/ORCHESTRATION.md).

## The program in brief

- **Main goal (Marc, 2026-11-05):** a generic parametric insurance module in Climate Risk Commons (CRC): `crc_sdk.parametric` in `crc-sdk`, with an exemplary notebook in `crc-docs`, contributed by PRs to RiskThinking's repositories. RiskThinking welcomes the module. With it, users:
  - create a parametric cover for a hazard and an asset;
  - analyse its effectiveness on several metrics (overall coverage, tail coverage, basis risk, …) and under different scenarios;
  - compare covers.

  It is agnostic about the asset(s), the impact function(s), the scenario(s), the optimisation goal, the payout function type (linear, stepwise, piecewise linear, …) and its parametrisation. It comes in two steps:
  1. **Phase 1:** the basic functionality and logic in CRC, plus the exemplary notebook.
  2. **Phase 2 (continuous):** multi-hazard (multi-dimensional) covers, the portfolio approach (optimising for a portfolio goal, as in the thesis) and analysis under different scenarios.
- **The thesis's two ideas carry over as features of the module.** The thesis had two ideas: tail-risk–optimised payout design (a weighted CVaR objective, solved as an LP) and portfolio-level calibration (payouts calibrated jointly across assets: individual, cluster and portfolio scopes).
  - Tail: the weighted CVaR of the uncovered loss is one of the module's optimisation goals, from Phase 1, next to MSE and expected uncovered loss.
  - Portfolio: joint calibration is the Phase 2 portfolio approach. A tail goal on the owner's total is the combination.
- **Priorities (Marc, 2026-11-05):**
  1. **CRC Contribution:** the main priority. The plan is in SPEC §8.
  2. **CLIMADA Contribution:** second, "to a lesser degree". The prototype (MAR-168) continues when CRC has no ready agent work.
  3. **Paused:** Foundation (the core backlog), Website & Blog, and Paper. They get no new dispatches. Their open PRs (#165, #7, #170) stay as they are, with no rebases and no merges. Fixing a red `main` is still allowed.
- **Repositories and what each is for** (D9, Marc, 2026-11-05):

  | Repository | What it is for |
  |---|---|
  | `marc272/crc-sdk`, a fork of `RiskThinking/crc-sdk`; integration branch `parametric` | Where `crc_sdk.parametric` is built. AGPL-3.0-or-later. Each phase ends in an upstream PR (Human, MAR-249) |
  | `marc272/crc-docs`, a fork of `RiskThinking/crc-docs`; branch `parametric` | The showcase notebook, plus a pipeline or skill if RiskThinking wants them. The notebook's terms are Marc's (2026-11-05) |
  | `marc272/parametric-insurance-design` (this repository) | The reference implementation and test oracle (the thesis-faithful core, and golden fixtures for the CRC module, MAR-245), the design record (ADR 0005, MAR-244), the CLIMADA prototype, and the paused tracks. `packages/crc` is dormant |

  Work in the forks follows "Working in the CRC forks" below.
- **The research questions stay with the paper, which is paused.** The publication rule uses them:
  - **RQ1, tail:** when does a tail-optimised (weighted-CVaR) design pay against MSE and E[U] designs?
  - **RQ2, portfolio:** when does joint calibration (portfolio or cluster scope) pay against calibrating each asset on its own, under each objective (MSE, E[U], weighted CVaR)? The use case is one risk owner with many sites, who cares about the total shortfall, so sites can cover each other.
  - **Combination (RQ1 × RQ2):** a weighted-CVaR objective calibrated jointly across one owner's sites.
- **Publication rule** (decided at C1, 2026-11-01; MAR-29). Every external output (the CRC module's docs and notebook, the CLIMADA module's text, the website, posts, READMEs and docs pages):
  - presents the method and the tool;
  - states the setup of every number shown: portfolio or asset, basis, basis-risk model, pricing and split;
  - uses numbers from out-of-sample runs on the annual basis;
  - RQ1 (tail): makes only conditional, mechanism-based statements tied to a stated setup (e.g. "on this asset, under pure pricing, …"). No general claim that tail optimisation outperforms;
  - RQ2 (joint calibration): method only, meaning what joint calibration is and what it optimises. No comparative claim, in either direction;
  - the combination: any statement involving joint calibration follows the RQ2 rule;
  - links no private Linear pages.

  The owner revisits the RQ2 rule after the Florida rerun (MAR-152 item 4).
- **Hard boundaries:**
  - `core` and `viz` never import an adapter;
  - the CRC module (`crc_sdk.parametric`) never imports `parametric_insurance_design`. Parity with the core is checked through golden fixtures (MAR-245);
  - the CLIMADA stream never touches CRC/VELO code or data;
  - every package keeps its licence (ADR 0001).

  In the fork, review enforces the CRC module's rule: the orchestrator checks that no file of the diff imports `parametric_insurance_design`. In this repository, CI enforces the import rules (MAR-76): `parametric_insurance_design` (core) and `parametric_insurance_design_viz` never import `parametric_insurance_design_crc` or `parametric_insurance_design_climada`; `parametric_insurance_design_climada` never imports `parametric_insurance_design_crc`; core never imports viz, except the lazy `importlib` call in `cli.py`'s `figures` command (MAR-110). The bans are ruff `TID251` (banned-api) in the `[tool.ruff]` table of `packages/core`, `packages/viz` and `packages/climada/pyproject.toml`, applied by `ruff check` in the `lint` job to src, tests and scripts. `scripts/check_import_boundaries.sh`, in the same job, proves they fire.
- **Current plan and status:** in Linear, at the [Program hub](https://linear.app/marc-prinzing/project/program-hub-1b757250497c). Your issue says why your piece matters. If it doesn't, ask.

## Sources of truth, in order

1. **Linear** (team MAR): what we aim to do, priorities, plan, decisions and status. For you, that means the issue you were given: its goal, scope and acceptance criteria.
2. [`docs/SPEC.md`](docs/SPEC.md): the *how* (method, architecture, data contract, standards). Binding. For the CRC module, the *how* is ADR 0005 (MAR-244) and crc-sdk's own docs.
3. ADRs in `docs/adr/`. ADR 0002 defines the core interfaces and the **module ownership map**. In a fork, the fork's own `AGENTS.md` is binding too ("Working in the CRC forks").

If these conflict, stop and escalate. Never resolve a conflict by editing the spec, an ADR or Linear yourself.

## Before you start

- Read your issue, the spec sections it cites, and ADR 0002. For an issue in a fork, read the fork's own `AGENTS.md` and ADR 0005 instead of ADR 0002.
- Confirm that every "blocked by" issue is Done and its PR is merged. If not, stop and report back.
- Linear status changes belong to the orchestrator. You report back to it; if you have Linear access, you may only comment on your own issue.

## Scope discipline

- **One issue = one branch = one PR.** Do only the issue you were given.
- Edit only the files your issue owns (ADR 0002 ownership map), plus new tests and docs for them. You may import other modules but must not edit them. If you need an interface change, stop and escalate.
- No drive-by refactors, formatting churn or unrelated cleanups. A new third-party dependency needs a one-line justification in the PR body.

## Branch, commits, PR

These rules are for this repository. In a fork, "Working in the CRC forks" below replaces the branch base, the commit format and the PR title.

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

## Working in the CRC forks

These rules apply to every issue whose work lands in `marc272/crc-sdk` or `marc272/crc-docs` (Marc, 2026-11-05; the CRC Contribution project description has the details). The rest of this file applies too, unless this section says otherwise.

**Where you work**

- The orchestrator creates your worktree in the fork clone and gives you its path. Work only there: use absolute paths, `git -C <worktree> …` for git, and `cd <worktree> && …` for the fork's own tools. Never edit the fork clone's own checkout, and never edit this repository in a fork issue.
- Your branch is the issue's Linear branch name, cut from the fork's `parametric`. Never commit to `main` or `parametric`. The fork's `main` mirrors upstream.

**Their rules are binding**

- Read the fork's own `AGENTS.md` first. It and the fork's checks are binding, together with this file. Where the two differ on code style or tooling, the fork's wins in the fork, because the code is written for upstream. Escalate any other conflict.
- crc-sdk:
  - checks: `uv run pytest -q`, `uv run mypy` (strict), `uv run ruff check . && uv run ruff format --check .`;
  - offline tests;
  - no I/O in builders or `explain()`;
  - atomic writes;
  - licence and provenance for every source;
  - no breaking changes to `__all__`.
- crc-docs: its `AGENTS.md`, and its tests (`uv run pytest -q`). Its CI checks only the agent skills, so the checks you run on the final head are the gate.

**Written for upstream**

- Code, docs and commit subjects follow their conventional-commit style, e.g. `feat(parametric): add the step payout`. No MAR IDs or Linear links in code or docs.
- The Linear ID goes in the fork PR's title and body, and in a `Refs: MAR-<n>` trailer on each commit.
- The fork has no `no-linear-urls` hook. Before each push, `git -C <worktree> diff origin/parametric... | grep -nE 'MAR-[0-9]+|linear\.app'` must print nothing.

**Self-contained, no new base dependencies, no data**

- The CRC module imports nothing from `parametric_insurance_design`. Parity with the core is checked through golden fixtures (MAR-245).
- Nothing new goes into crc-sdk's base install. The solver is an optional extra, chosen in ADR 0005.
- No CRC Open data is committed (CC BY-NC). Tests are offline, on small synthetic fixtures.

**Branches and PRs**

- Push your branch to the fork (`git -C <worktree> push -u origin <branch>`) and open the PR inside the fork, with base `parametric`. Push early, as in this repository.
- Every `gh pr` command names the fork: `gh pr create --repo marc272/crc-sdk --base parametric --head <branch> --draft …`, and the same `--repo` on `gh pr view`, `edit`, `ready` and `checks`. Without `--repo`, `gh` in a fork clone can resolve to RiskThinking's repository.
- PR title: `[MAR-<n>] <conventional-commit subject>`. PR body: as in this repository (the issue, the acceptance criteria with evidence, deviations, follow-ups), plus the summary of the fork's checks on the final head.
- Done means: every acceptance criterion is evidenced, and the fork's CI is green on the PR. In crc-docs, where CI doesn't run the tests, the fork's checks pass on the final head and their summary is in the PR body.

**No contact with RiskThinking**

- Never open issues, PRs or discussions on RiskThinking's repositories, never push to the `upstream` remote, and never contact RiskThinking. Those steps are Marc's (MAR-249), and so are the upstream PRs.
- Never connect to RiskThinking's services, such as the CDT Express MCP server in crc-docs' `.mcp.json`. Read upstream only through `git fetch upstream`.
- The publication rule applies to the module's docs and to the notebook. The CLIMADA stream stays CRC-free.

## Engineering standards (SPEC §4.3)

These are this repository's standards. In a fork, its own standards apply ("Working in the CRC forks").

- Core supports Python 3.11–3.13. Type hints everywhere. Numpy-style docstrings.
- ruff (lint and format) and pyright (basic) clean. pytest with meaningful tests. Core coverage ≥ 85 %.
- Determinism: pass `np.random.Generator` objects explicitly. No global seeds.
- **No silent failures:** raise typed errors or record failures explicitly. Never `except: pass`, and never drop rows, entities or runs quietly.
- No library logic in notebooks.
- Public files use plain issue IDs (`MAR-123`), never Linear URLs; only the agent files are exempt (pre-commit hook `no-linear-urls`). A new page under `docs/` gets its `docs/README.md` line in the same PR (hook `docs-index`).
- Never commit data beyond small fixtures. Downloads go through scripts with checksums.
- Environments:
  - uv workspace: `core`, `viz`, `crc`.
  - pixi: `packages/climada`.
  - Never add CLIMADA to the uv workspace or CRC to the pixi env.
  - `packages/climada` must never import `packages/crc`. The CLIMADA stream is CRC-free.

## Definition of done

- CI is green on the PR (in a fork, see "Working in the CRC forks"), or, while Actions minutes are exhausted, `scripts/ci_local.sh` passes on the PR head and its summary is in the PR body (under "Local CI (GitHub Actions minutes exhausted)"; runbook "Merge policy").
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
- Publish, post, submit or send anything outside this repository and the two forks (`marc272/crc-sdk`, `marc272/crc-docs`): discussions, issues or PRs on other repos (RiskThinking's included), arXiv, blogs, LinkedIn, emails.
- Contact RiskThinking, or push to a fork's `upstream` remote.
- Archive, delete or rewrite the history of any repository, or delete data.
- Change Linear projects, milestones, labels or other issues. Edit decisions in the spec.
- Work on issues labelled **Human**, beyond the "Agent may prepare" part you were explicitly given.

## Research issues

- Record the config hash for every result you cite.
- Report **observations, not conclusions**. Interpretation belongs to the human (checkpoint C1, positioning, manuscript).
