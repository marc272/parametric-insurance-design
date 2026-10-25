@AGENTS.md

## Orchestrator

If you coordinate work rather than implementing a single issue, you are the orchestrator. Read [`docs/ORCHESTRATION.md`](docs/ORCHESTRATION.md) and start every session at the Linear **Program hub**: https://linear.app/marc-prinzing/project/program-hub-1b757250497c. Read its description and its latest status update. Start or resume the loop with the `/orchestrate` skill.

**Merge authorisation.** On 2026-10-25 (MAR-80) the owner, Marc Prinzing, authorised the orchestrator to squash-merge (`gh pr merge <n> --squash`) agent PRs in `marc272/parametric-insurance-design` without a human approval, under the runbook's "Merge policy":

- the orchestrator has reviewed the PR;
- all CI checks are green;
- the PR doesn't belong to a Human or Gate issue.

Workers never merge. Never use `--admin`, force-push or push to `main`.
