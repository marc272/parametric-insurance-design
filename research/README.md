# research/

The working area of the paper: the configs, scripts, notes and small derived data of the research runs ([`docs/SPEC.md`](../docs/SPEC.md) §4). The paper itself isn't written yet.

| Folder | What it holds |
|---|---|
| `configs/` | Configs of the research runs |
| `configs/climada/` | CLIMADA build configs of research EventSets (the cat-in-a-circle radius sensitivity), built from `packages/climada` ([README](configs/climada/README.md)) |
| `scripts/` | Scripts that build the research EventSets, run the designs and write the tables and figures |
| `data/` | Small tables and figures derived from the runs, some with their checksums. Raw downloads and built EventSets stay in the git-ignored `data/` at the repository root |
| `notes/` | One note per study: its setup, its inputs and the observations |
| `checkpoints/` | The notes of the program's checkpoints, with their figures |
| `lit/` | Literature notes, positioning and the bibliography |

- The notes and checkpoints are working records, not published results. They link the project's private Linear workspace, whose pages don't open for visitors.
- Every design result cites the config hash it came from.
- Library logic belongs in `packages/core`, not here, and paper experiment code never goes into the core.
- Licence: the code is BSD-3-Clause, under the repository's [LICENSE](../LICENSE). Derived data follows the terms of its sources, recorded in [`docs/data-sources.md`](../docs/data-sources.md).

The repository's [README](../README.md) has the project's status.
