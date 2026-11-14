# Working agreement for agents

The program is built by several worker agents coordinated by an orchestrator agent, in this repository, in two forks of RiskThinking's repositories and in a fork of CLIMADA's `climada_petals`. The human owner is Marc Prinzing. This file is **binding for every worker**, in this repository and in the forks. The orchestrator follows [`docs/ORCHESTRATION.md`](docs/ORCHESTRATION.md).

## The program in brief

- **Main goal (Marc, 2026-11-05):** a generic parametric insurance module in Climate Risk Commons (CRC): `crc_sdk.parametric` in `crc-sdk`, with an exemplary notebook in `crc-docs`, contributed by PRs to RiskThinking's repositories. Its home in crc-sdk is confirmed. With it, users:
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
  2. **CLIMADA Contribution:** second, "to a lesser degree". Since 2026-11-08: a generic parametric insurance module for CLIMADA, `climada_petals.engine.parametric`, and a detailed tutorial, designed in ADR 0006 and built in the fork `marc272/climada_petals`. Its issues get a slot when CRC has no ready agent work.
  3. **Paused:** Foundation (the core backlog), Website & Blog, and Paper. They get no new dispatches. Their open PRs (#165, #7, #170) stay as they are, with no rebases and no merges. Fixing a red `main` is still allowed.
- **Repositories and what each is for** (D9, Marc, 2026-11-05):

  | Repository | What it is for |
  |---|---|
  | `marc272/crc-sdk`, a fork of `RiskThinking/crc-sdk`; integration branch `parametric` | Where `crc_sdk.parametric` is built. AGPL-3.0-or-later. Each phase ends in an upstream PR (Human, MAR-249) |
  | `marc272/crc-docs`, a fork of `RiskThinking/crc-docs`; branch `parametric` | The showcase notebook, plus a pipeline or skill if RiskThinking wants them. The notebook's terms are Marc's (2026-11-05) |
  | `marc272/climada_petals`, a fork of `CLIMADA-project/climada_petals`; integration branch `parametric`, cut from upstream `develop` | Where `climada_petals.engine.parametric`, its tutorial and its API docs are built (ADR 0006; K-10, MAR-309). GPL v3. Phase 1 ends in one upstream PR to `develop` (Human, K-05, MAR-51) |
  | `marc272/parametric-insurance-design` (this repository) | The reference implementation and test oracle (the thesis-faithful core, and golden fixtures for the CRC module, MAR-245, and for the CLIMADA module, MAR-312), the design records (ADR 0005, MAR-244; ADR 0006, MAR-48), the CLIMADA prototype, frozen after its port (K-14), and the paused tracks. `packages/crc` is dormant |

  Work in the CRC forks follows "Working in the CRC forks" below, and work in the CLIMADA fork "Working in the CLIMADA fork".
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
  - the CLIMADA module (`climada_petals.engine.parametric`) never imports `parametric_insurance_design` or `parametric_insurance_design_climada`. Parity with the core is checked through golden fixtures (`parity/climada/`, MAR-312);
  - the CLIMADA stream never touches CRC/VELO code or data;
  - the petals prototype (`packages/climada/src/petals_parametric`, MAR-168) never imports the core, the CLIMADA adapter, viz or CRC, statically or dynamically, because it moves into `climada_petals`. Its `ruff.toml` (TID251, job `lint`) and `packages/climada/tests/test_petals_parametric_isolation.py` (job `test (climada, pixi)`) enforce this. The other direction is no boundary: the adapter may import the prototype, so it has no ban;
  - every package keeps its licence (ADR 0001).

  In the forks, review enforces the modules' rules: the orchestrator checks that no file of the diff imports `parametric_insurance_design`, nor, in the CLIMADA fork, `parametric_insurance_design_climada`. In this repository, CI enforces the import rules (MAR-76): `parametric_insurance_design` (core) and `parametric_insurance_design_viz` never import `parametric_insurance_design_crc` or `parametric_insurance_design_climada`; `parametric_insurance_design_climada` never imports `parametric_insurance_design_crc`; core never imports viz, except the lazy `importlib` call in `cli.py`'s `figures` command (MAR-110). The bans are ruff `TID251` (banned-api) in the `[tool.ruff]` table of `packages/core`, `packages/viz` and `packages/climada/pyproject.toml`, applied by `ruff check` in the `lint` job to src, tests and scripts. `scripts/check_import_boundaries.sh`, in the same job, proves they fire.
- **Current plan and status:** in Linear, at the [Program hub](https://linear.app/marc-prinzing/project/program-hub-1b757250497c). Your issue says why your piece matters. If it doesn't, ask.

## Sources of truth, in order

1. **Linear** (team MAR): what we aim to do, priorities, plan, decisions and status. For you, that means the issue you were given: its goal, scope and acceptance criteria.
2. [`docs/SPEC.md`](docs/SPEC.md): the *how* (method, architecture, data contract, standards). Binding. For the CRC module, the *how* is ADR 0005 (MAR-244) and crc-sdk's own docs. For the CLIMADA module, it is ADR 0006 (MAR-48) and CLIMADA's developer guide.
3. ADRs in `docs/adr/`. ADR 0002 defines the core interfaces and the **module ownership map**. In a CRC fork, the fork's own `AGENTS.md` is binding too ("Working in the CRC forks"). Petals has none, so in the CLIMADA fork CLIMADA's own rules are binding, as "Working in the CLIMADA fork" gives them.

If these conflict, stop and escalate. Never resolve a conflict by editing the spec, an ADR or Linear yourself.

## Before you start

- Read your issue, the spec sections it cites, and ADR 0002. For an issue in a CRC fork, read the fork's own `AGENTS.md` and ADR 0005 instead of ADR 0002. For an issue in the CLIMADA fork, read "Working in the CLIMADA fork" and ADR 0006 instead.
- Confirm that every "blocked by" issue is Done and its PR is merged. If not, stop and report back.
- Linear status changes belong to the orchestrator. You report back to it; if you have Linear access, you may only comment on your own issue.

## Scope discipline

- **One issue = one branch = one PR.** Do only the issue you were given.
- Edit only the files your issue owns (ADR 0002 ownership map), plus new tests and docs for them. You may import other modules but must not edit them. If you need an interface change, stop and escalate.
- No drive-by refactors, formatting churn or unrelated cleanups. A new third-party dependency needs a one-line justification in the PR body.

## Branch, commits, PR

These rules are for this repository. In a fork, "Working in the CRC forks" or "Working in the CLIMADA fork" below replaces the branch base, the commit format and the PR title.

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
  - checks, as its `AGENTS.md` and CI run them: `uv sync --locked --all-extras` first, then `uv run --locked --all-extras pytest -q`, `uv run --locked --all-extras mypy` (strict), and `uv run --locked --all-extras ruff check . && uv run --locked --all-extras ruff format --check .`. pytest, mypy and ruff are only in the `test` extra, and highspy in `parametric`;
  - offline tests;
  - no I/O in builders or `explain()`;
  - atomic writes;
  - licence and provenance for every source;
  - no breaking changes to `__all__`.
- crc-docs:
  - checks, as the `checks` job of its `ci.yml` runs them: `uv sync --locked` first, then `uv run pytest -q`, and `uv run ruff check pipelines tests tools && uv run ruff format --check pipelines tests tools`;
  - two lines of its `AGENTS.md` differ on purpose. We sync without `--extra velo`, as its `ci.yml` does: the extra adds only `velo-sdk`, which only the tests that need a CDT API key import, and agents never run those. And we leave out the `CRC_DOCS_LIVE=1` run ("No contact with RiskThinking"). So the tests in `tests/test_live.py` are skipped, which is expected;
  - Actions are off on `marc272/crc-docs` (Marc, 2026-11-08), so nothing runs on your PR, and the checks you run on the final head are the merge gate. They stay off: the `live` job in upstream's `ci.yml` reaches RiskThinking's data, and `ci.yml` runs on a weekly `schedule` and on `push` to `main` as well as on `pull_request`.

**Written for upstream**

- Code, docs and commit subjects follow their conventional-commit style, e.g. `feat(parametric): add the step payout`. No MAR IDs or Linear links in code or docs.
- The Linear ID goes in the fork PR's title and body, and in a `Refs: MAR-<n>` trailer on each commit. The `Refs` line and any `Co-Authored-By` line go in the same final paragraph, with no blank line between them: otherwise git doesn't parse `Refs` as a trailer.
- The fork has no `no-linear-urls` hook. Before each push, `git -C <worktree> diff origin/parametric... | grep -nE 'MAR-[0-9]+|linear\.app'` must print nothing.

**Self-contained, no new base dependencies, no data**

- The CRC module imports nothing from `parametric_insurance_design`. Parity with the core is checked through golden fixtures (MAR-245).
- Nothing new goes into crc-sdk's base install. The solver is an optional extra, chosen in ADR 0005.
- No CRC Open data is committed (CC BY-NC). Tests are offline, on small synthetic fixtures.

**Branches and PRs**

- Push your branch to the fork (`git -C <worktree> push -u origin <branch>`) and open the PR inside the fork, with base `parametric`. Push early, as in this repository.
- Every `gh pr` command names the fork: `gh pr create --repo marc272/crc-sdk --base parametric --head <branch> --draft …`, and the same `--repo` on `gh pr view`, `edit`, `ready` and `checks`. Without `--repo`, `gh` in a fork clone can resolve to RiskThinking's repository.
- PR title: `[MAR-<n>] <conventional-commit subject>`. PR body: as in this repository (the issue, the acceptance criteria with evidence, deviations, follow-ups), plus the summary of the fork's checks on the final head. Pass it with `--body-file`: a `gh` command line that names a RiskThinking repository (`RiskThinking/<repo>`, in a flag, a URL or a body) is denied.
- Done means: every acceptance criterion is evidenced, and the fork's CI is green on the PR. In crc-docs, where Actions are off, the fork's checks pass on the final head and their summary is in the PR body.

**No contact with RiskThinking**

- Never open issues, PRs or discussions on RiskThinking's repositories, never push to the `upstream` remote, and never contact RiskThinking. Those steps are Marc's (MAR-249), and so are the upstream PRs.
- Never connect to RiskThinking's services, such as the CDT Express MCP server in crc-docs' `.mcp.json`. Read upstream only through `git fetch upstream`. The one exception is the downloads for the parametric notebooks in crc-docs (Marc, 2026-11-08 and 2026-11-12, MAR-377):
  - the notebooks: the primer (MAR-299), notebook B on how the module works (MAR-375), and the showcases on how a cover ages (MAR-335), choosing the index (MAR-352), the budget frontier (MAR-353) and rain and heat (MAR-342). The downloads are for those notebooks only;
  - the public CRC Open release, from `https://data.riskthinking.ai/crc-open`, as crc-docs' `pipelines/crc_open_pipeline.py` and crc-sdk's `crc_open` provider read it. It is RiskThinking's service, hence the exception;
  - ERA5, as crc-docs reads it through crc-sdk's `era5` provider: Google Cloud's public Zarr copies (`gs://gcp-public-data-arco-era5` and `gs://weatherbench2`), read anonymously, with no CDS account. It is not a RiskThinking service, and it is named here so that the permission is explicit;
  - no credentials, and nothing downloaded is committed;
  - not covered: anything that needs `CRC_DOCS_LIVE=1`, a CDT API key, the `velo` extra or the CDT Express MCP server.
- Never set `CRC_DOCS_LIVE=1` in crc-docs: it runs all of `tests/test_live.py`. This rule has no exception, the notebooks' downloads (MAR-377) included.
- Never create tags or releases, never run workflows by hand, and never turn Actions back on in `marc272/crc-docs`. crc-sdk's release workflow runs on any pushed `v*` tag.
- The publication rule applies to the module's docs and to the notebook. The CLIMADA stream stays CRC-free.

## Working in the CLIMADA fork

These rules apply to every issue whose work lands in `marc272/climada_petals`, the fork of `CLIMADA-project/climada_petals` where `climada_petals.engine.parametric`, its tutorial and its API docs are built (K-10, MAR-309: Marc's answers of 2026-11-08 and 2026-11-09). The design is ADR 0006 (D12, MAR-48), and its §14 is the plan. The rest of this file applies too, unless this section says otherwise. CLIMADA's conventions differ from crc-sdk's in most respects, so "Working in the CRC forks" does not apply here.

**Where you work**

- The orchestrator creates your worktree at `/Users/marcprinzing/Parametric_Insurance/forks/worktrees/climada_petals-mar-<n>`, from the clone `/Users/marcprinzing/Parametric_Insurance/forks/climada_petals`, and gives you its path. Work only there: use absolute paths, `git -C <worktree> …` for git, and `cd <worktree> && …` for the checks. Never edit the clone's own checkout, and never edit this repository in a fork issue.
- Your branch is the issue's Linear branch name, cut from the fork's `parametric`. Never commit to `main`, `develop` or `parametric`. The fork's `main` and `develop` mirror upstream, and `parametric`, cut from upstream `develop`, changes only through merged PRs. A ruleset blocks deletion and non-fast-forward pushes on all three.
- Your environment, logs and PR-body drafts go in `<worktree>-notes/`, never in the worktree or the shared session scratchpad.

**CLIMADA's rules are binding**

Petals has no `AGENTS.md`. Its rules are CLIMADA's developer guide (the `doc/development/` pages of core, which petals follows), its `CONTRIBUTING.md` and `AI_POLICY.md` (in core), and petals' own `.pylintrc`, `Makefile` and PR template. They are binding in the fork, together with this file. Where they differ from this file on code style or tooling, theirs win in the fork, because the code is written for upstream. Escalate any other conflict. In short:

- Code: numpydoc docstrings, `from_*` constructors, a module `LOGGER`, `plot_*` functions that return their axes, and item-style column access (`df["col"]`). CLIMADA classes don't inherit from external libraries' classes. At most 7 arguments per function (`max-args=7`), 1,000 lines per module and 100 characters per line (pylint), with black's layout.
- Tests: unit tests next to the code, in `climada_petals/engine/parametric/test/`, each at most 2 s, with no external resources. Integration tests go in `climada_petals/test/`. New code has 100 % line coverage.
- Formatting: black and isort with `--profile black --filter-files`, at the versions of core's `.pre-commit-config.yaml` (black 24.4.2, isort 5.13.2); no trailing whitespace; every file ends in one newline. Petals has no pre-commit config of its own (none in the tree at `3f57dcf`), and most of its files don't follow them: black would reformat 112 of the 144 Python files and notebooks in `climada_petals/` and `doc/tutorial/`, and isort flags 103 files. So these apply to the module's files only. Never reformat other petals files.
- Records: the module's API page under `doc/climada_petals/`, the tutorial in `doc/tutorial/`, and the entries in `CHANGELOG.md` and `AUTHORS.md`, in the issues ADR 0006 §14 assigns them to.

**Written for upstream**

- Commit subjects follow CLIMADA's guide: imperative, capitalised, at most 50 characters, no final period, and naming what they change, e.g. `Add StepPayout to engine.parametric`. Wrap the body at 72 characters and say what and why. No MAR IDs or Linear links in code, docs or commit subjects.
- The Linear ID goes in the fork PR's title and body, and in a `Refs: MAR-<n>` trailer on each commit. The `Refs` line and any `Co-Authored-By` line go in the same final paragraph, with no blank line between them.
- CLIMADA's `AI_POLICY.md` closes upstream PRs that list an LLM product as co-author. Marc's decision (Marc, 2026-11-10, MAR-310): commits and PRs in the fork keep the usual attribution lines. The upstream PR (K-05) is Marc's: he opens it from a fresh branch with the work squashed, authored by him and with no LLM co-author tags, as `AI_POLICY.md` allows, once he can explain and defend every line. So the first upstream PR is kept to the core module.
- PR title: `[MAR-<n>] <subject>`, with the subject in the commit style above.
- Before each push, `git -C <worktree> diff origin/parametric... | grep -nE 'MAR-[0-9]+|linear\.app'` must print nothing.

**Self-contained, no new dependencies, no data**

- The module never imports `parametric_insurance_design` or `parametric_insurance_design_climada`, statically or dynamically. Parity with the core goes through K-13's fixtures, `parity/climada/` in this repository, which K-18 and K-19 copy into the module's test data. The copies are CC0-1.0 (ADR 0001, amendment 4).
- The stream stays CRC-free: no crc-sdk code or data is read, copied or ported. crc-sdk is AGPL, and petals is GPL v3. ADR 0005's text may be read for concepts and metric definitions only.
- No new dependency beyond ADR 0006 (D10: scipy's HiGHS for the LPs and `SLSQP` for MSE, no new package). The port keeps cvxpy until K-19 removes it. Petals' `pyproject.toml` and `requirements/` stay as they are, unless your issue says otherwise.
- No data committed beyond small test files: K-13's fixtures stay within 200 KB. Downloads from CLIMADA's public Data API, with no credentials, are allowed for K-12 and the tutorial (Marc, K-10, answer 3) and for the tests of the merge gate below (Marc, 2026-11-10, MAR-310). Nothing downloaded is committed.

**The merge gate**

Actions are off on the fork (K-10), so nothing runs on your PR. These checks are the merge gate: you run them on the final head and paste their summary into the PR body, and the orchestrator re-runs them on the head it merges. They were fixed from a run on `parametric` at `3f57dcf` on 2026-11-10, on osx-arm64 (MAR-310; `linux-64` was not tried).

*The environment, once per worktree* (about 2 minutes once conda's package cache is warm). It is built as upstream's `testing.yml` builds it: core's `requirements/env_climada.yml`, then petals' on top, then core `develop` and petals installed from source, on Python 3.12 (upstream's CI runs 3.12 and 3.13). conda-forge's own climada and petals packages aren't used: its climada 6.2.0 build needs Python 3.11, and its petals pins climada 6.1 (K-12, Q1). The clone of core is read-only: never change its remotes, commit or push there.

```bash
WT=/Users/marcprinzing/Parametric_Insurance/forks/worktrees/climada_petals-mar-<n>
NOTES=$WT-notes
git clone --depth 1 --branch develop https://github.com/CLIMADA-project/climada_python.git "$NOTES/climada_python"
~/miniforge3/bin/mamba create -y -p "$NOTES/env" -f "$NOTES/climada_python/requirements/env_climada.yml" python=3.12 make "gfortran>=13"
~/miniforge3/bin/mamba env update -y -p "$NOTES/env" -f "$WT/requirements/env_climada.yml"
"$NOTES/env/bin/python" -m pip install "$NOTES/climada_python[dev]" -e "$WT" "black[jupyter]==24.4.2" "isort==5.13.2" "pytest-socket==0.7.0"
git -C "$NOTES/climada_python" log -1 --format='core develop %h %cs'
```

black, isort and pytest-socket are the gate's tools, not petals dependencies. The editable install leaves `climada_petals.egg-info/` in the worktree, and the checks leave caches and logs; petals' `.gitignore` covers them. Record the core commit that the last line prints.

*The checks*, from the worktree. Run them in one shell, because variables don't carry over between tool calls. Each says when it passes.

```bash
cd "$WT"
export PATH="$NOTES/env/bin:$PATH" MPLBACKEND=Agg DYLD_FALLBACK_LIBRARY_PATH="$NOTES/env/lib"
MOD=climada_petals/engine/parametric
```

`MPLBACKEND=Agg` keeps `plt.show()` from blocking (the default backend on macOS is `macosx`). `DYLD_FALLBACK_LIBRARY_PATH` is for osx-arm64, where conda-forge's `c-blosc2` links `liblz4` by a Homebrew path and pytables fails to load (K-12, Q1).

1. **Petals' unit tests**, as upstream's CI runs them (`make unit_test`: everything outside `climada_petals/test/`), without two test modules and 13 tests that reach services other than CLIMADA's Data API. It takes about 60 s. It passes with no failure and no error: on `3f57dcf`, 316 passed, 2 skipped and 13 deselected.

   ```bash
   GIT_ALLOW_PROTOCOL=file PIP_NO_INDEX=1 python -m pytest -q -p no:cacheprovider \
     --allow-hosts=climada.ethz.ch,data.iac.ethz.ch --allow-unix-socket \
     --ignore=climada_petals/test \
     --ignore=climada_petals/entity/exposures/test/test_black_marble.py \
     --ignore=climada_petals/hazard/test/test_wildfire.py \
     -k "not test_plot_warning or test_plot_warning_meteoswiss" \
     --deselect=climada_petals/hazard/emulator/test/test_geo.py::TestGeo::test_hazregion_centroids \
     --deselect=climada_petals/hazard/emulator/test/test_geo.py::TestGeo::test_init_hazregion \
     --deselect=climada_petals/hazard/test/test_flood.py::TestRiverFlood::test_NATearth_country_flood \
     --deselect=climada_petals/hazard/test/test_low_flow.py::TestLowFlowNETCDF::test_combine_nc \
     --deselect=climada_petals/hazard/test/test_low_flow.py::TestLowFlowNETCDF::test_filter_events \
     --deselect=climada_petals/hazard/test/test_low_flow.py::TestLowFlowNETCDF::test_load_FR_all \
     --deselect=climada_petals/hazard/test/test_relative_cropyield.py::TestRelativeCropyield::test_load_EU_all \
     --deselect=climada_petals/hazard/test/test_relative_cropyield.py::TestRelativeCropyield::test_set_percentile_to_int \
     --deselect=climada_petals/hazard/test/test_relative_cropyield.py::TestRelativeCropyield::test_set_rel_yield \
     --deselect=climada_petals/hazard/tc_surge_geoclaw/test/test_geoclaw_runner.py::TestRunner::test_init \
     --deselect=climada_petals/hazard/tc_surge_geoclaw/test/test_tc_surge_geoclaw.py::TestHazardInit::test_init \
     --deselect=climada_petals/hazard/tc_surge_geoclaw/test/test_geoclaw_runner.py::TestFuncs::test_load_topography \
     climada_petals/
   ```

   What is left out, and why:
   - the two `--ignore`d modules, the test that `-k` leaves out and the first 11 `--deselect`ed tests call cartopy's `natural_earth`, which downloads Natural Earth's shapefiles from `naturalearth.s3.amazonaws.com` into `~/.local/share/cartopy`. The agents' sandbox refuses writes to that folder, so there they fail before any download, and elsewhere they would download;
   - `-k` stands in for `--deselect` there because `--deselect` matches by prefix, and would also drop `test_plot_warning_meteoswiss`, which needs no download;
   - the last, `test_load_topography`, calls petals' `setup_clawpack`, which pip-installs Clawpack from `github.com/clawpack` and builds it with gfortran. `GIT_ALLOW_PROTOCOL=file` and `PIP_NO_INDEX=1` make any such install fail instead (`fatal: transport 'https' not allowed`);
   - `--allow-hosts` lets a test reach only the Data API's two hosts. `test_warn.py`, `test_low_flow.py`, `test_tc_rainfield.py` and three files of `tc_surge_geoclaw/test/` download small test data sets from it, into `~/climada/data/`. pytest-socket guards each test's setup, call and teardown, not collection: two of those files download at import.
2. **The module's unit tests**: offline, at most 2 s each, and 100 % line coverage. It passes when every test passes, the durations list after "slowest durations" is empty, and coverage is 100 %.

   ```bash
   python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
     --durations=0 --durations-min=2 \
     --cov="$MOD" --cov-config=.coveragerc --cov-report=term-missing --cov-fail-under=100 \
     "$MOD"
   ```

   Petals' `.coveragerc` leaves the `test/` folders out of the coverage. From K-23 on, the module's own integration tests (`climada_petals/test/test_parametric*.py`) run too, with the Data API as their only network: `python -m pytest -q -p no:cacheprovider --allow-hosts=climada.ethz.ch,data.iac.ethz.ch --allow-unix-socket climada_petals/test/test_parametric*.py`. K-23 confirms that command here.
3. **pylint with petals' `.pylintrc`** (read from the worktree root). It passes when the `grep` prints nothing: no message of any category on a file of the module.

   ```bash
   python -m pylint "$MOD" > "$NOTES/pylint.log"
   grep -E "^$MOD/" "$NOTES/pylint.log"
   ```

   CLIMADA treats high-priority warnings like test failures, allows no new medium ones, and doesn't let the number of low ones grow (developer guide, "Continuous Integration"). Its Jenkins reads pylint's letters as error for F, high for E, medium (normal) for W and low for C, R and I. Every file of the module is new, so the gate allows none. pylint's exit status is never 0 here: petals' `.pylintrc` disables 54 messages that pylint 4 no longer knows, and it reports them as `R0022` against `.pylintrc` itself, with a `UserWarning` on stderr. Those lines are petals' own and don't count. `make lint`, which lints the whole package into `pylint.log` and ends in `|| true`, gives the baseline: on `3f57dcf`, 940 messages in 47 modules (17 E, 77 W, 300 R, 546 C), rated 8.64/10, in 24 s.
4. **black and isort** on the module's files (`--check`: they change nothing). They pass with exit status 0. From K-04 on, add the tutorial's notebook to the black list: black formats notebooks too.

   ```bash
   git ls-files -z -- "$MOD/*.py" 'climada_petals/test/test_parametric*.py' | xargs -0 python -m black --check --diff
   git ls-files -z -- "$MOD/*.py" 'climada_petals/test/test_parametric*.py' | xargs -0 python -m isort --profile black --filter-files --check-only --diff
   ```
5. **Whitespace, IDs and commit subjects** against `parametric`. Each command passes when it prints nothing.

   ```bash
   git -C "$WT" diff --check origin/parametric...HEAD
   git -C "$WT" diff origin/parametric... | grep -nE 'MAR-[0-9]+|linear\.app'
   git -C "$WT" log --format=%s origin/parametric..HEAD | grep -nE 'MAR-[0-9]+|.{51,}'
   ```

   The first finds trailing whitespace and blank lines at the end of a file; a file that lacks its final newline shows as `\ No newline at end of file` in `git diff`. The last finds a MAR ID or more than 50 characters in a commit subject.

*The summary* in the PR body gives the head commit, the core commit, Python and platform, and one line per check: the pytest counts and time of 1 and 2, the coverage and the durations list of 2, the number of the module's pylint lines (0), black's and isort's result, and that the three commands of 5 printed nothing.

*What the gate leaves out.* Petals' full suite (`make integ_test` and `make test`, on `climada_petals/test/`) is not run, and neither are `make data_test` and `make notebook_test`. Those 11 files test petals' other modules, and they reach services beyond CLIMADA's Data API: NASA's Black Marble imagery, Natural Earth, ECMWF's forecast FTP (with a login from petals' config), the MRIO databases through pymrio, and Clawpack from GitHub, among others (read from the code, not run). Running them needs network access to those services, and in places their logins, which agents never use. Whether to run them, and who runs them, is Marc's decision.

**Branches and PRs**

- Push your branch to the fork (`git -C <worktree> push -u origin <branch>`) and open the PR inside the fork, with base `parametric`: `gh pr create --repo marc272/climada_petals --base parametric --head <branch> --draft --title "…" --body-file <file>`. Push early, as in this repository.
- Every `gh pr` command names the fork, written out: `--repo marc272/climada_petals`, on `gh pr view`, `edit`, `ready` and `checks` too. Without it, `gh` in a fork clone can resolve to CLIMADA-project's repository. A hook refuses a repository from a variable.
- PR body: as in this repository (the issue, the acceptance criteria with evidence, deviations, follow-ups), plus the gate's summary on the final head. Pass it with `--body-file`.
- Done means: every acceptance criterion is evidenced, and the merge gate passes on the final head, with its summary in the PR body.

**No contact with CLIMADA's maintainers**

- Never open issues, PRs or discussions on CLIMADA-project's repositories, never comment there, never push to the `upstream` remote, and never contact CLIMADA's maintainers. Those steps are Marc's: K-01, the maintainer discussion, and K-05, the upstream PR to `develop`.
- Read upstream only through `git fetch upstream` in the clone, and core only through the read-only clone in your notes folder.
- Never set credentials or sign in to anything, not for the Data API (it needs none) and not for the services other petals modules use.
- Never create tags or releases, never run workflows by hand, and never turn Actions on in `marc272/climada_petals`. Upstream's `ci.yml` runs on every push and checks out CLIMADA-project's repositories, and its other workflows are release steps that need secrets.
- The publication rule applies to the module's docs and to the tutorial. The CLIMADA stream stays CRC-free.

**The prototype is frozen.** After the port (K-14, MAR-313), `packages/climada/src/petals_parametric` in this repository gets no new work: fixes and features go to the fork. Its isolation rules stay: the `ruff.toml` ban (TID251) and `packages/climada/tests/test_petals_parametric_isolation.py`.

## Engineering standards (SPEC §4.3)

These are this repository's standards. In a fork, the fork's Python versions, tooling and style come first where they differ ("Working in the CRC forks", "Working in the CLIMADA fork"); determinism, no silent failures, no library logic in notebooks and no data hold there too.

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

- CI is green on the PR (in a fork, see "Working in the CRC forks" or "Working in the CLIMADA fork"), or, while Actions minutes are exhausted, `scripts/ci_local.sh` passes on the PR head and its summary is in the PR body (under "Local CI (GitHub Actions minutes exhausted)"; runbook "Merge policy").
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
- Publish, post, submit or send anything outside this repository and the three forks (`marc272/crc-sdk`, `marc272/crc-docs`, `marc272/climada_petals`): discussions, issues or PRs on other repos (RiskThinking's and CLIMADA-project's included), arXiv, blogs, LinkedIn, emails.
- Contact RiskThinking or CLIMADA's maintainers, or push to a fork's `upstream` remote.
- Start a session anywhere but here (`start_session` only without `cwd`, `host`, `preset`, `environment` or `repository`, and with no `target` other than `"local"`), or create, change or run scheduled tasks or cloud routines.
- Archive, delete or rewrite the history of any repository, or delete data.
- Change Linear projects, milestones, labels or other issues. Edit decisions in the spec.
- Work on issues labelled **Human**, beyond the "Agent may prepare" part you were explicitly given.

## Research issues

- Record the config hash for every result you cite.
- Report **observations, not conclusions**. Interpretation belongs to the human (checkpoint C1, positioning, manuscript).
