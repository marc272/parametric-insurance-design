# ADR 0004: Repository structure for external presentation

- Status: **Proposed**. This is a draft for the owner's decision. Nothing in it is decided.
- Date: 2026-10-31
- Decision issue: MAR-162 (D8). It feeds MAR-163 (concept docs), MAR-164 (READMEs), MAR-165 (examples) and MAR-168 (the location of the petals prototype).
- Prepared by a worker agent from `main` at `f74f123`. **Q2 and Q3 were revised after the design review MAR-161** (PR #99, `docs/reviews/core-design-review.md`; findings cited as "review F<n>"). The review settles both, so they are no longer provisional.

## Context

Marc (2026-10-31): the website and the posts will link to this repository. It should read as a library built around the thesis's two ideas: tail-risk minimisation, and portfolio-level (joint) calibration. The audit on MAR-162 found:

- stale READMEs;
- no page for either idea, and no runnable example;
- a flat public API that also exports the thesis noise layer and the unimplemented robust stubs;
- research configs inside `packages/climada`;
- the agent tooling at the root.

Fixed constraints:

- **Hard boundaries (ADR 0001):** core and viz never import an adapter, the CLIMADA stream never touches CRC, and every package keeps its licence. CI enforces the import rules with ruff `TID251`, `scripts/check_import_boundaries.sh`, the core's `tests/test_import_boundaries.py` and viz's `tests/test_imports.py`.
- **ADR 0002's ownership map:** one owner issue per file, so that parallel agents never edit the same file. Its rows are keyed by file path.
- **ADR 0003:** one site tool, Quarto + OJS on GitHub Pages.
- **The publication rule (AGENTS.md)** applies to every README, page and example output.

The costs below follow from these facts, checked in the code at `f74f123`:

| # | Fact | Where |
|---|---|---|
| F1 | `run_id` hashes four things: the config hash, the checksum of the EventSet *as loaded*, the core's package version and the solver policy. The config hash leaves out `eventset.path`, `output`, the labels and the sweeps | `experiment/runner.py` (`run_key`), `experiment/config.py` (`config_hash`) |
| F2 | `EventSet.content_hash()` covers the metadata, including each `TransformRecord`'s `function` (qualified name) and `version` (the producer's version). `noise.add_noise` and `EventSet.select_locations` record their own `__module__` | `eventset.py`, `noise.py` |
| F3 | 127 Python files import `parametric_insurance_design.<module>` by path | grep over `packages/`, `parity/`, `research/`, `scripts/` |
| F4 | `pid.solve` and `pid.evaluate` are modules. Tests import `from parametric_insurance_design import solve` as the module. Viz's import test forbids the module paths `…problem`, `…solve`, the names `problem`, `solve` and `cli`, and the attribute `build_problems` | `tests/test_solve.py`, `packages/viz/tests/test_imports.py` |
| F5 | `import parametric_insurance_design` doesn't load `experiment/`: the runner, store and config are reached as `parametric_insurance_design.experiment.<module>` | `__init__.py` |
| F6 | CLIMADA build configs resolve their paths relative to the file. The build record keeps input file names and SHA256s, not the config's path. Research records the SHA256 of the config files it used | `packages/climada/…/config.py`, `pipeline.py`; `research/data/cat-in-circle-radius-sensitivity/checksums.json`, `research/data/p06-storm-eventset/checksums.json` |
| F7 | Viz reads only the result store (SPEC §3.1 C6). Its figure functions take store runs (`ResultReader`), not `SolveResult`s | `packages/viz` |

What these facts mean for every question below:

- Moving a core module changes no run id and no config hash (F1).
- Moving `noise.py` or `eventset.py` does change the content hash of noised and location-subset EventSets (F2). That hash is the manifests' `prepared_eventset`.
- A core version bump changes every run id (F1).
- A version bump of the CLIMADA adapter changes the content hash of every adapter build (F2).

## Q1. Root layout and first impression

The root today:

- folders: `.claude/`, `.github/`, `docs/`, `packages/`, `parity/`, `research/`, `scripts/`, `showcase/`, `site/`;
- files: `AGENTS.md`, `CLAUDE.md`, `LICENSE`, `README.md`, `pyproject.toml`, `uv.lock` and dotfiles.

GitHub lists the folders first and renders the README below the file list. `AGENTS.md` and `CLAUDE.md` must stay at the root for the tooling, and `.claude/skills/orchestrate/` must stay where Claude Code finds it.

| Option | What | Cost and consequences |
|---|---|---|
| **1A. Keep and signpost** | Nothing moves. The README gets a short section, "How this repository is built": worker agents and an orchestrator, Linear as the plan, the owner decides. It links `AGENTS.md`, `docs/ORCHESTRATION.md` and the ADRs | README text only (MAR-164), and no link breaks. The agent workflow stays visible, which is honest |
| 1B | 1A, and move `docs/ORCHESTRATION.md` next to the skill (`.claude/ORCHESTRATION.md`) | Breaks the links in both `CLAUDE.md` files (the workspace one is outside the repository), `AGENTS.md`, SPEC §12, the orchestrate skill and the Program hub description in Linear. It removes one file from `docs/`, which a visitor sees only after the README |
| 1C | 1A, plus a `CONTRIBUTING.md` for human contributors | GitHub links it from the issue and PR forms. It duplicates `AGENTS.md`, which already addresses everyone who contributes, so two documents must be kept in step |

Also part of the first impression:

- `site/` and `showcase/crc/` hold only a README today. Keep both folders: they are planned outputs, and the README refresh says what is planned and where it is tracked.
- MAR-168's petals prototype goes inside `packages/climada` (GPL-3.0, pixi env), as MAR-168 already states.
- GitHub's "About" box (description, website URL, topics) is a repository setting. That's an owner action, outside this ADR.

**Recommendation: 1A.** It costs nothing, breaks nothing and is truthful. Hiding the tooling would spare visitors one glance at the file list, and it would cost a round of link fixes in the repository, the workspace and Linear.

## Q2. Public API by story

Today `pid` re-exports the data contract and the shared types (`EventSet`, `Basis`, `Sample`, `SolveResult`, …) and imports every module. So `pid.noise` and `pid.robust` sit next to `pid.objectives`, although robust's two entry points raise `NotImplementedError("MAR-34")` and `("MAR-35")` (review F10).

To design one payout, a user calls `pid.problem.build_problems(...)`, then `pid.solve.solve(built, pricing=...)` for each problem. The same pricing has to be passed twice to get the exact premium (MAR-143), and nothing checks that the two match (review F16). The review's F16 follow-up makes `BuiltProblem` carry its pricing, so `solve(built)` records the exact premium without the argument, and a differing `pricing` argument raises `ComponentConfigError`.

| Option | Top level | Cost and consequences |
|---|---|---|
| 2A | As today, minus `noise` and `robust` | `__init__` stops importing the two modules, but `import parametric_insurance_design.noise` still works. Breaks `pid.noise` and `pid.robust` as attributes; nothing in the repository uses them that way. Needs an ADR 0002 §1 amendment ("imports every module" becomes "every module but these two"), and `tests/test_package_exports.py` changes |
| **2B. The stories' names** | 2A, plus the components of both stories: `StepPayout`; `Individual`, `Cluster`, `Portfolio`, `ThesisWardClustering`; `MSE`, `ExpectedUncovered`, `WeightedCVaR`; `PurePremium`, `CostOfCapitalLoad`; `Budget` | Additive, so no import breaks. Needs an ADR 0002 §1 amendment: the top level becomes a curated list, changed only by a public-API issue (the rule ADR 0002 already gives `__init__.py`). No name collides with a module, because the classes are CamelCase |
| 2C | 2B, plus the solver functions as top-level names (`build_problems`, `solve`) | `pid.solve` would become the function and shadow the module (F4). That breaks `pid.solve.SolverPolicy`, `pid.solve.DEFAULT_POLICY` and `from parametric_insurance_design import solve`. Viz's import test would also have to forbid the new routes |
| **2D. A thin convenience API** | 2B, plus one function: `pid.design(eventset, scope, payout, objective, *, basis, pricing=PurePremium(), constraints=(), sample=None, policy=DEFAULT_POLICY) -> tuple[SolveResult, ...]`. It builds every problem of the scope and solves each one | A new module, `workflow.py`, with its own owner row; it doesn't edit `problem.py` or `solve.py`. After review F16, `design` is a plain composition, `solve(b, policy)` for each `b` of `build_problems(...)`, and the pricing is given once. Its remaining value is one call per scope (the individual scope has one problem per asset) with the basis stated. The new contract needs an ADR 0002 amendment. `basis` stays required, so every call states its setup. Viz's import test adds `design` and `workflow` to its forbidden names. The low-level path (`pid.problem`, `pid.solve`) stays for LP-level work |

Under every option, these stay where they are:

- **Evaluation:** `pid.evaluate.kpis`, `pid.evaluate.exceedance_curves`, `pid.splits.holdout`, `pid.splits.year_block_kfold` and `pid.bootstrap`. The module names read as namespaces, and `pid.evaluate` couldn't become a function without 2C's collision.
- **The experiment layer** (config → store → figures). It is public too, but it stays at `parametric_insurance_design.experiment.{config,runner,store,sweeps}`, next to the CLI (F5). Viz reads only this layer (F7).
- **Extension points:** `pid.interfaces`, `pid.records` and `pid.errors` stay module attributes, for anyone who writes a new objective or scope.
- **Private modules** stay private. The review's F13 follow-up adds `_validation.py` for the shared validators. Its leading underscore keeps it out of `__init__`, `__all__` and the exports test, which already skips `_` modules.

Two modules leave the top level (review F10):

- **`robust`** is left out of `__init__` and `__all__` until MAR-34 implements R1, and its module docstring says so. It isn't renamed to `_robust`: a rename would change the file path in its ownership rows (MAR-34, MAR-35), and MAR-34 would have to rename it back.
- **`noise`** isn't thesis-only. SPEC §6.3 keeps the noise layer as the baseline next to the vulnerability draws, and the runner uses it. It leaves the top level but stays supported, and its module docstring calls it that baseline.

Names that carry more than one meaning (review F12) stay as they are:

- `Portfolio` is the scope, but "portfolio" is also the `problem_id` of both joint scopes, a KPI level and a KPI subject.
- `Budget(loading=)` is κ, while `CostOfCapitalLoad` is a different load.
- `WeightedCVaR` is a mixture of mean and CVaR, not a CVaR with weights.

The review proposes no rename before v1, only a glossary in MAR-163, because the components' `name`s and the config keys (for example `weighted_cvar` and `loading`) enter the configs, the config hashes and so the run ids. This ADR follows that, so three of the listed names (`Portfolio`, `Budget`, `WeightedCVaR`) keep a meaning that needs the glossary. Exporting the classes at the top level makes them more visible, so the glossary should be in place when they are exported. A rename of a Python class alone wouldn't touch configs or hashes, but after 0.1.0 is on PyPI (Q7) it would also need a deprecation.

**Recommendation: 2B + 2D.** The stories' vocabulary goes at the top level, plus one `design()` call. Implement 2D after review F16, so that `design` never passes the pricing twice. `robust` and `noise` come off the top level as above; robust comes back once MAR-34 implements it.

Illustration only (the real quickstart belongs to MAR-164 and MAR-165). The review's F1 follow-up is a correctness fix to `StepPayout` that adds a `below_attachment="zero" | "first_bin"` option, so this call may gain that argument later; the list of names doesn't change.

```python
import parametric_insurance_design as pid

es = pid.EventSet.from_parquet("parity/tests/data/thesis_eventset")
train, test = pid.splits.holdout(es)
results = pid.design(
    es,
    pid.Portfolio(),
    pid.StepPayout(attachment=20.0, limit=70.0, n_bins=15),
    pid.WeightedCVaR(alpha=0.9, beta=0.95),
    basis=pid.Basis.ANNUAL,
    constraints=(pid.Budget(1.0),),
    sample=train,
)
```

## Q3. Module layout

Today the core has 20 flat modules plus the `experiment/` subpackage (ADR 0002 §1). The design review found the module boundaries **sound**: the import graph matches the ownership map. Its one structural proposal is a private flat module, `_validation.py` (review F13). Review F13 also has `clustering` reuse `riskmeasures.lower_quantile`, which is an import between existing modules, not a new boundary.

| Option | What | Cost and consequences |
|---|---|---|
| **3A. Keep flat** | The stories show through the API (Q2), the API reference's sections and the concept pages' code maps, not through folders | None. The ownership map stays as it is |
| 3B | Subpackages, as a hard move. For example: `design/` (payout, scopes, clustering, index, objectives, pricing, constraints, problem, solve), `evaluation/` (evaluate, riskmeasures, bootstrap, splits) and `data/` (eventset, basis, noise). `interfaces`, `errors`, `records`, `robust`, `cli` and `experiment/` stay where they are | See "Costs of 3B" below the table |
| 3C | 3B with shims: the old modules stay as one-line re-exports | No import breaks now. But 20 shim modules double what a visitor sees, which is the opposite of the goal. The shims need deprecation warnings and a removal date. F2's hash changes happen anyway, because the functions' `__module__` moves |

Costs of 3B:

- **One large, blocking PR.** It rewrites the imports of about 127 files (F3), which belong to many owner issues. So it is serialised against every open PR and forces each of them to rebase.
- **Contract and test updates.** The 34 core rows of the ownership map are rewritten. Viz's forbidden-module list must name the new paths, or the boundary test silently stops guarding (F4). `test_package_exports.py`, which lists only top-level modules, changes too. The core's import-boundary test already walks subpackages.
- **Hashes.** Noised and location-subset EventSets get new content hashes (F2). Run ids, config hashes and the committed parity reports don't change (F1).
- **Every text that names a module** must be updated: the CLIMADA adapter, parity, the research scripts, the docs, and the Linear issues that name `objectives.py` and the like.
- **Nobody outside breaks yet,** because the package isn't on PyPI.

**Recommendation: 3A.** A 20-module package doesn't need folders to be legible, and the flat layout is what lets parallel agents own files without conflicts. The review supports this: the boundaries are sound, and `_validation.py` adds one private module with one new ownership row, and nothing public. If the owner wants subpackages, the time is before the first PyPI release (Q7), while no external user can break, and as 3B rather than 3C.

## Q4. Docs layout and API reference

`docs/` today holds `SPEC.md`, `ORCHESTRATION.md`, `data-sources.md`, `adr/` and `methodology/` (the evaluation features). Two folders are planned: `docs/concepts/` (MAR-163) and `docs/reviews/` (MAR-161's default).

**Layout**

| Option | What | Cost and consequences |
|---|---|---|
| **4A. Separate by an index, not by folder** | Add `docs/concepts/` and `docs/reviews/`, and a `docs/README.md` with two lists. "Understand the method": concepts, then methodology, then data sources. "How it's built": SPEC, ADRs, ORCHESTRATION, reviews. Nothing moves | No link breaks. GitHub renders `docs/README.md` when a visitor opens `docs/` |
| 4B | Move the developer docs to `docs/dev/` (SPEC, `adr/`, ORCHESTRATION, reviews) | Breaks the links in about 20 repository files, both `CLAUDE.md` files and the orchestrate skill. It also breaks many Linear issue descriptions and worker briefs, which cite `docs/SPEC.md` and `docs/adr/0002-…` by path |
| 4C | The user docs move into the Quarto site (`site/`), and `docs/` stays developer-only | The concept and methodology pages would no longer render on GitHub next to the code they describe. The site isn't deployed yet (MAR-53 is Todo), so the pages would have no home until it is. Rendering `docs/concepts/` into the site later stays possible (MAR-53's call; unverified) |

The concept pages are plain GitHub Markdown, with math in `$…$`. They render on GitHub now and can be pulled into the site later.

**API reference.** This ADR adds no dependency. The PR that adds one carries its justification. Facts checked on 2026-10-31 on PyPI and GitHub:

| Option | What | Facts | Cost and consequences |
|---|---|---|---|
| **R1. quartodoc in the Quarto site** | Generates `.qmd` reference pages from the docstrings (`quartodoc build`, then `quarto render`) | MIT. Latest release 0.11.1 (2025-06-10); last push to `machow/quartodoc` on 2025-12-08. Numpy docstrings are its default parser. Its runtime dependencies include griffe, pydantic, black, requests, watchdog and plum-dispatch | One site tool (ADR 0003). Its sections can group the flat modules by story, which supports 3A. It renders in the site's theme, including dark mode. It needs a `docs` dependency group in the root `pyproject.toml` (never a core dependency) and a Python step in the site build, which ADR 0003 had kept optional. Upstream has been quiet for about 11 months, so pin the version; the reference is a non-critical page |
| R2. pdoc | Standalone HTML, copied into the site as static files | MIT-0. Latest 16.0.0 (2025-10-27); last push on 2026-07-01. Four dependencies (Jinja2, pygments, MarkupSafe, markdown2). Numpy docstrings via `--docformat numpy` | The smallest dependency. But it has its own theme and looks unlike the site, and it is a second output to keep in step |
| R3. MkDocs + mkdocstrings, or Sphinx | A second documentation site | — | Contradicts ADR 0003's rationale of one site tool |
| R4. None for now | The concept pages' code maps and the docstrings (`help()`) | — | No cost, but external readers get no browsable reference |

**Recommendation: 4A and R1.** Add quartodoc once the site skeleton (MAR-53) exists, and render only Q2's public API. R2 is the fallback if the pinned quartodoc breaks with the pinned Quarto.

## Q5. Research artefacts and dead code

What the configs in `packages/climada/configs/` are used for:

| Configs | Used by |
|---|---|
| `thesis*.yaml` (5) | The adapter tests, `docs/methodology/vulnerability.md` and the parity adapter check. They stay |
| `florida_counties.yaml`, `florida_counties_cat_in_circle.yaml` | The D2 paper EventSets and the tests. They stay |
| `florida_counties_no_draws.yaml` | The Florida build without draws: the base of the radius configs, and the IRIS reference of the dropped STORM scenario. `test_storm.py` loads it. It stays, but its header comment is stale |
| `florida_counties_cat_in_circle_{50,75,100,150}km_no_draws.yaml` | Only the MAR-133 radius sensitivity (research): `research/data/cat-in-circle-radius-sensitivity/`, its note and the script's docstring. No test loads them |
| `florida_counties_storm.yaml`, `florida_counties_storm_cat_in_circle.yaml` | The STORM scenario S_1, dropped when D7 was revisited (MAR-62, 2026-10-31). Two tests in `test_storm.py` load them, and `research/data/p06-storm-eventset/checksums.json` records their SHA256 |

**Radius configs.** Move them, byte-identical, to `research/configs/climada/`:

- That folder is three levels deep, like `packages/climada/configs/`. So every relative path in the configs still resolves, their SHA256s in `checksums.json` stay valid, and the EventSets they build don't change (F6).
- Their comments still name sibling configs as `configs/…`. A short `README.md` in the new folder says that these mean `packages/climada/configs/…`.
- The research README, the research note and the script's docstring that cite the old paths get the new ones.
- The script `cat_in_circle_radius_sensitivity.py` and its test stay in `packages/climada`. They import the GPL adapter and run in the pixi CI job. Moving them into BSD `research/` would need an ADR 0001 amendment, like the one for `showcase/crc/`, and a pixi test path for `research/`.

**STORM configs.**

| Option | What | Cost and consequences |
|---|---|---|
| 5a. Keep | As they are | Two shipped configs describe a scenario the paper no longer has (their comments say "S_1 of the robust design"). They stay ready if STORM becomes reachable |
| **5b. Remove** | Delete both configs and the two tests that only load them. Keep `storm.py`, the `tracks:` selection, the equivalence test on synthetic files and `compare_hazard_return_levels.py` | The loader stays tested and ready, as MAR-62 decided. Reviving STORM means writing one config: `florida_counties_no_draws.yaml` plus a `tracks:` block, which the README shows. The p06 note records the deleted files' SHA256s and the last commit that has them (`f74f123`) |
| 5c. Park in research | Move them byte-identical to `research/configs/climada/` | Keeps the provenance, but the stale S_1 comments stay. The package test would have to read `research/`; `test_portfolio_litpop.py`, which reads the D2 note, is the one precedent |

In the same step:

- `packages/climada/README.md`: the STORM section becomes "STORM loader (parked)".
- `florida_counties_no_draws.yaml`: the stale header comment about STORM is rewritten. That changes the file's SHA256, which the p06 checksums record, so the p06 note records the old and new values. The EventSet doesn't change (F6).

**Other dead code:** nothing is decided here. MAR-161 (review F14) found no STORM code in the core, and no unimplemented core code beyond the `robust` stubs; it didn't do a full dead-code scan. `robust.py` is planned work (MAR-34), not dead code. `THESIS_POLICY` and `noise.py` serve parity and the thesis baseline.

**Recommendation:** move the radius configs as described, and choose **5b** for STORM.

## Q6. Examples

The constraints come from MAR-165 and MAR-164:

- two scripts: the tail-risk objective, and portfolio calibration;
- each under about 80 lines, using only the public API, writing to a temp dir and printing its setup lines;
- a CI smoke job under about 2 minutes;
- MAR-164's quickstart comes from example 1.

The figures come from viz, and viz reads only the result store (F7). So an example that draws a figure has to go through the experiment layer.

| Option | Where | Cost and consequences |
|---|---|---|
| **6A. `examples/` at the root** | `README.md` and `quickstart.py` (the Python API, `pid.design`; it is the README quickstart verbatim). Then `tail_risk_objective.py` and `portfolio_calibration.py`: config → `run_config` into a temp store → viz figures. Plus `test_examples.py` and a `ruff.toml` with the adapter bans (`TID251`) | See "Costs of 6A" below the table |
| 6B. Executed Quarto pages in `site/` | `.qmd` pages that run Python at build time | Puts Python execution into the site build, which ADR 0003 avoided. Ties the examples to the site's deploy cadence, and GitHub doesn't run them |
| 6C. Notebooks | `examples/*.ipynb`, run with nbmake (SPEC §4.3: "Tutorial notebooks run in CI") | A new test dependency (nbmake) and notebook diffs in review. A better fit for K-04's CLIMADA tutorial (MAR-50), which lives in `packages/climada` anyway |

Costs of 6A:

- **CI:** one step, "Test examples", in the `test (workspace, …)` jobs, and the same in `scripts/ci_local.sh`. No coverage gate.
- **Checks:** `examples` joins pyright's `include`.
- **Licence:** BSD under the root licence. ADR 0001's table gets one line for `examples/`.
- **Runtime (an estimate, not measured):** the fixture is 6,057 rows × 9 assets. The 1,860 parity runs took about 65 minutes serially, so about 2 s a run; a dozen runs fit the budget.

The examples import only core and viz, never an adapter, so they stay BSD and CRC-free.

**Recommendation: 6A.**

## Q7. Release readiness

All four distributions are `0.1.0.dev0` today. CI builds the four wheels and checks their licence metadata.

**Version**

| Option | What | Cost and consequences |
|---|---|---|
| **7a** | Core and viz go to `0.1.0`; the adapters stay at `0.1.0.dev0` | Every cached run id changes (F1). Result stores recompute on their next run; for the parity store that's about 17 minutes at `--jobs 8`. The run ids and the version line of `parity/REPORT.md` are stale until it is regenerated. Config hashes don't change, so research citations by config hash stay valid. The adapter builds keep their content hashes (F2) |
| 7b | All four go to `0.1.0` | As 7a, plus every CLIMADA adapter build gets a new content hash (F2). A rebuilt D2 EventSet then no longer matches `research/data/d2-florida-eventset/checksums.json`, and any config that pins its checksum fails with `ChecksumMismatchError` |
| 7c | Stay at `.dev0` until the paper | Nothing changes, but the first impression says "dev" |

Timing: bump after the C1 analysis runs that the bump would invalidate (MAR-158 is in progress), in a PR that also regenerates the parity report.

**CHANGELOG.** One root `CHANGELOG.md` in the Keep a Changelog style: a section per release, with a subsection per distribution. The orchestrator writes it at release time from the merged PR titles. Per-PR entries are rejected, because parallel PRs would all conflict on the file. The first entry, 0.1.0, summarises F-01 to F-12 and states setups, not results. A `CITATION.cff` (GitHub's "Cite this repository") can come with it; the DOI follows with the paper (P-09).

**PyPI.** Publishing is a Human step.

| Option | What | Cost and consequences |
|---|---|---|
| **P1. Core and viz on PyPI at 0.1.0, after a TestPyPI dry run** | A tag-triggered GitHub Actions workflow with PyPI trusted publishing, so no token is stored | Owner steps: create the PyPI and TestPyPI projects, register the trusted publisher, push the tag. Readers of the posts can then `pip install parametric-insurance-design`, and the name is reserved. It was free on 2026-10-25 (ADR 0001); recheck at release. The PyPI page shows the core README, so the publication rule applies there too |
| P2. Not now | A GitHub release and tag only; install from git | No owner step. Readers need `pip install git+https://…`, and the name stays unreserved |

The adapters stay unpublished under both options: CLIMADA comes from conda-forge, and the CRC adapter depends on the CRC SDK's terms. The Zenodo DOI comes with the paper (P-09) either way.

0.1.0 fixes the import paths people will copy, so Q2 and Q3 come first.

**Recommendation: 7a, a root CHANGELOG written at release time, and P1 at website v1 (MAR-60), for core and viz only.**

## Not verified

- No quartodoc prototype was built, so R1 is untested with a pinned Quarto.
- The example runtime is an estimate from the parity timings.
- Whether a core version bump needs a `pixi lock` in `packages/climada`. The core is an editable path dependency there.
- Whether `docs/concepts/` can be rendered into the Quarto site without copying (4C).
- MAR-161's review is still on PR #99 (not merged). The "review F<n>" citations are to its head, `b144b43`.

## Decisions (owner)

One answer per question. "As recommended" is enough.

- **Q1, root layout** (recommended: 1A). Answer:
- **Q2, public API** (recommended: 2B + 2D, after review F16; `robust` and `noise` off the top level, per review F10). Answer:
- **Q3, module layout** (recommended: 3A). Answer:
- **Q4, docs layout and API reference** (recommended: 4A and R1, fallback R2). Answer:
- **Q5, research configs and STORM** (recommended: move the radius configs to `research/configs/climada/`; 5b). Answer:
- **Q6, examples** (recommended: 6A). Answer:
- **Q7, release** (recommended: 7a, a root CHANGELOG at release time, P1 at MAR-60 for core and viz). Answer:

## Migration plan (if the recommendations are accepted)

The steps are PR-sized and ordered by dependency. Steps 2, 4 and 5 can run in parallel. Changes to `pyproject.toml`, the lockfiles and CI are serialised (ORCHESTRATION.md).

The review's other follow-ups (F1, F13 and the rest) are filed from MAR-161 and aren't steps here:

- Review F13 and step 2 both edit `problem.py`, so they are sequenced.
- Review F1 edits `payout.py`, which no step here touches.

1. **Record D8.** Files: this ADR (status and answers), `docs/SPEC.md` §4 (the tree gains `examples/`, `docs/concepts/` and `research/configs/`) and §11 (a D8 row), and ADR 0001's licence table (an `examples/` row). Acceptance: SPEC §11 lists D8 with its outcome.
2. **`BuiltProblem` carries its pricing (review F16).** It comes first, so that `design` never passes the pricing twice.
   - Files: `problem.py`, `solve.py`, their tests, and the ADR 0002 amendment (the `BuiltProblem` fields are contract).
   - Acceptance: `solve(built)` records `pricing.premium_value` without a `pricing` argument, and a `pricing` argument that differs from the built one raises `ComponentConfigError`.
3. **Public API (Q2, including review F10).** Blocked by steps 1 and 2. Review F10's acceptance is folded in here, with no separate issue.
   - Files: `packages/core/src/…/__init__.py`; a new `workflow.py`; the module docstrings of `robust.py` and `noise.py`; `tests/test_package_exports.py` and a new `tests/test_workflow.py`; `packages/viz/tests/test_imports.py` (the forbidden names only); the ADR 0002 §1 and §10 amendment.
   - Acceptance: on the fixture, for every scope × objective, `pid.design` gives the results of `build_problems` plus `solve`. The exports test pins the top-level list. `robust` and `noise` aren't in `pid.__all__`, and `__init__` imports neither (only `experiment/` imports `noise`). Robust's docstring says it is unimplemented until MAR-34, and noise's calls it the SPEC §6.3 baseline. Viz's import test rejects `pid.design`.
4. **Research configs and STORM (Q5).**
   - Files: `research/configs/climada/` (the four moved configs and a README), and the two deleted `packages/climada/configs/florida_counties_storm*.yaml`.
   - Also: two tests in `packages/climada/tests/test_storm.py`; the header of `florida_counties_no_draws.yaml`; `packages/climada/README.md`; the docstring path in `scripts/cat_in_circle_radius_sensitivity.py`; `research/data/cat-in-circle-radius-sensitivity/README.md`, `research/notes/cat-in-circle-radius-sensitivity.md`, `research/data/p06-storm-eventset/README.md` and `research/notes/p06-storm-eventset.md`; ADR 0002's MAR-32 row.
   - Acceptance: the moved configs' SHA256s equal the recorded ones, and `test (climada, pixi)` is green.
5. **Docs index (Q4).** Files: a new `docs/README.md`. Acceptance: every file in `docs/` is linked from it. MAR-161 adds `docs/reviews/` (PR #99), and MAR-163 adds its pages to the index.
6. **Concept docs (MAR-163).** Blocked by step 3, because the code maps name the public API.
   - Files: `docs/concepts/*.md`.
   - Includes review F12's glossary of "portfolio", "loading" and "weighted CVaR".
7. **Examples (MAR-165, Q6).** Blocked by step 3.
   - Files: `examples/` (README, `quickstart.py`, the two story scripts, `test_examples.py`, `ruff.toml`); one step in `.github/workflows/ci.yml` and in `scripts/ci_local.sh`; pyright's `include` in the root `pyproject.toml`.
   - Acceptance: the step runs every example on the fixture in under 2 minutes, and CI is green.
8. **READMEs (MAR-164, Q1).** Blocked by steps 6 and 7.
   - Files: the root and package READMEs; the `site/`, `research/` and `showcase/crc/` READMEs. One test is appended to `examples/test_examples.py`.
   - Acceptance: the README quickstart equals `examples/quickstart.py` (that test), there's a "How this repository is built" section, and no README claims a false status.
9. **Docstring pass (review F11).**
   - Order: blocked by steps 2 and 3 and by the review's F13 follow-up, so that it reads the final code. It comes before steps 10 and 11, because the reference renders the docstrings and 0.1.0 ships them.
   - Files: the docstrings of the core's top-level modules only. This needs an orchestrator waiver across owners.
   - Acceptance: no Linear IDs or decision history in the core's docstrings, except pointers to ADRs and `docs/methodology/`; the stale statements the review lists are fixed; ruff and pyright are clean.
10. **API reference (Q4, R1).** Blocked by MAR-53 and steps 3 and 9.
    - Files: `site/_quarto.yml` (the quartodoc section); the root `pyproject.toml` (a `docs` group with a pinned quartodoc) and `uv.lock`; one step in the site workflow.
    - Acceptance: the site preview has a reference page for every public name of Q2, grouped by story.
11. **Version 0.1.0 (Q7).** Blocked by steps 3, 8 and 9, and by MAR-158's runs.
    - Files: the versions in `packages/core/pyproject.toml` and `packages/viz/pyproject.toml`; `uv.lock` (and `packages/climada/pixi.lock` if needed); `CHANGELOG.md`; optionally `CITATION.cff`; the regenerated `parity/REPORT.md` and `parity/reports/`.
    - Acceptance: CI's wheels carry 0.1.0, and the regenerated parity report has the committed report's findings.
12. **Release workflow (Q7).** Blocked by step 11.
    - Files: a new `.github/workflows/release.yml` (tag-triggered; TestPyPI, then PyPI; trusted publishing).
    - Acceptance: the dry run on TestPyPI installs and imports.
    - Human: create the projects, register the publishers, push `v0.1.0`, approve the publish.
