@AGENTS.md

## Orchestrator

If you coordinate work rather than implementing a single issue, you are the orchestrator. Read [`docs/ORCHESTRATION.md`](docs/ORCHESTRATION.md) and start every session at the Linear **Program hub**: https://linear.app/marc-prinzing/project/program-hub-1b757250497c. Read its description and its latest status update. Start or resume the loop with the `/orchestrate` skill.

**Merge authorisation.** The owner, Marc Prinzing, authorised the orchestrator to squash-merge agent PRs without a human approval:

- in `marc272/parametric-insurance-design` (2026-10-25, MAR-80): `gh pr merge <n> --squash`;
- in `marc272/crc-sdk` and `marc272/crc-docs`, PRs into the `parametric` branch (2026-11-05): `gh pr merge <n> --repo marc272/<fork> --squash`;
- in `marc272/climada_petals`, PRs into the `parametric` branch (2026-11-08): `gh pr merge <n> --repo marc272/climada_petals --squash`.

In each case, under the runbook's "Merge policy":

- the orchestrator has reviewed the PR;
- all CI checks are green (in crc-docs and climada_petals, whose Actions are off, the fork's own checks re-run by the orchestrator: runbook "Merge policy");
- the PR doesn't belong to a Human or Gate issue.

The orchestrator also keeps `parametric` current by merging upstream `main` (in climada_petals, upstream `develop`) into it (Marc, 2026-11-05), never by a rebase (runbook "Keeping `parametric` current").

Workers never merge. Nothing is ever merged upstream by an agent: the upstream PRs to RiskThinking's repositories are Marc's (MAR-249). Never use `--admin`, force-push, or push to any `main`, or to `develop` in climada_petals, ours or a fork's.
