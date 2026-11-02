# Documentation

There are two ways into these pages:

- **[Understand the method](#understand-the-method)** explains what the library does and how it evaluates a payout design.
- **[How it's built](#how-its-built)** shows how the repository is specified, decided and built.

To install the library and run the tests, see the [repository README](../README.md).

## Understand the method

Read the concepts first, then the methodology, then the data sources. These pages describe the method and the tool. They don't claim that either idea, or the two combined, outperforms the alternatives.

### Concepts

These pages explain the two ideas the library is built on, as the code implements them. The [concepts index](concepts/README.md) lists them and has a glossary of the terms that carry more than one meaning in the code.

- [The tail-risk objective](concepts/tail-risk-objective.md): the uncovered loss, the weighted-CVaR objective α·CVaR_β(U) + (1 − α)·E[U], why the design problem is a linear program, and the premium budget.
- [Portfolio calibration](concepts/portfolio-calibration.md): the individual, portfolio and cluster scopes, and cross-coverage for one risk owner with several assets.
- [Combining the two ideas](concepts/combination.md): the weighted-CVaR objective on the owner's total uncovered loss in one joint design problem, how the two ideas interact, and which view answers which owner's question.

### Methodology

These pages explain how a design is evaluated. Each one names the code and the config section it describes.

- [The evaluation basis](methodology/annual-basis.md): annual, event and event-conditional outcomes, and what each one means for the premium budget and for β.
- [Out-of-sample evaluation](methodology/out-of-sample.md): holdout and k-fold splits by contiguous blocks of simulation years.
- [Confidence intervals](methodology/bootstrap.md): the block bootstrap over years.
- [Pricing](methodology/pricing.md): the pure premium and the cost-of-capital load.
- [Allocating a joint payout to assets](methodology/payout-allocation.md): why per-asset KPIs of a joint design need a rule, and the `value` and `loss` rules.
- [Vulnerability uncertainty](methodology/vulnerability.md): loss draws from a prior on the `v_half` parameter of the Emanuel impact function, in the CLIMADA adapter.

### Data

- [Data sources](data-sources.md): the data the project uses, and the licence and terms of each source.

## How it's built

Worker agents build this repository, and an orchestrator agent coordinates them:

- Each worker implements one planned issue in one pull request.
- The orchestrator plans the work, delegates it to workers, reviews the pull requests and merges them.
- The owner, Marc Prinzing, makes the decisions.

The plan, the decisions and their status are tracked in Linear. That workspace is private, so the Linear links in some of these files don't open for visitors.

- [`AGENTS.md`](../AGENTS.md): the working agreement that binds every worker. It covers scope, branches and pull requests, the engineering standards, the publication rule and when to escalate. The root `CLAUDE.md` loads it for Claude Code.
- [`ORCHESTRATION.md`](ORCHESTRATION.md): the orchestrator's runbook. It covers the loop, delegation to workers, the merge policy and owner alerts. The [`/orchestrate` skill](../.claude/skills/orchestrate/SKILL.md) starts the loop.
- [`SPEC.md`](SPEC.md): the specification. It covers the method, the architecture, the EventSet data contract, the engineering standards and the decision log.
- [Architecture decision records](adr/):
  - [ADR 0001](adr/0001-name-and-licence.md): the project name and the licence of each package.
  - [ADR 0002](adr/0002-core-interfaces.md): the core interfaces, the module layout and the map of which issue owns each file.
  - [ADR 0003](adr/0003-website-stack.md): the website stack and hosting.
  - [ADR 0004](adr/0004-repository-structure.md): the repository structure for external presentation, including this index.
- [Reviews](reviews/):
  - [Core design review](reviews/core-design-review.md): the tail and portfolio formulations, checked against the spec and the thesis, with ranked findings and proposed follow-ups.
