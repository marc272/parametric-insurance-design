# Data sources

The data this project uses, and the terms each comes with. Data licences are separate from code licences (ADR 0001).

## Rules

- **No data is committed**, except small test fixtures. Downloads go through scripts that check checksums (`AGENTS.md`, `docs/SPEC.md` §4.3).
- Every EventSet records its source and licence in `metadata.json` (`docs/SPEC.md` §5).
- Data derived from a source keeps that source's terms, unless the source says otherwise.
- **Never guess a licence.** An entry is "verified" only when its licence was read from the primary source; record the date and the URL you read it from. Until then it stays "to verify", with the issue that will verify it.

## Sources

Started on 2026-10-25 (MAR-6) from what `docs/SPEC.md` and ADR 0001 state. Only the IRIS licence has been verified from its primary source so far (MAR-9, see [IRIS](#iris-licence-check-mar-9)); the other "Checked" cells are empty. The other source URLs were checked to resolve on 2026-10-25; they do not establish the licence.

| Source | Used for | Licence / terms | Source URL | Committed to the repo | Status | Checked |
|---|---|---|---|---|---|---|
| Climate Risk Commons (CRC) Open data | CRC showcase (`packages/crc`, `showcase/crc/`) | CC BY-NC 4.0, unless covered by the owner's agreement (as stated in ADR 0001) | to verify | No | To verify from the primary source: MAR-41 | — |
| VELO/CDT asset database | CRC showcase; candidate paper portfolio (D2) | The owner's licence (SPEC §1). Never committed | Licensed access only | Never | Terms to verify: MAR-41 | — |
| IRIS (Imperial College Storm Model) synthetic tropical cyclone event set | Hazard catalogue for the CLIMADA adapter and the thesis parity data | **The records differ** (MAR-72): **CC0 1.0** on the figshare item records of both files we download (figshare API and DataCite), but **CC BY 4.0** on the collection's DataCite record. Not resolved: owner to decide which governs. The data descriptor article is CC BY 4.0 | Dataset: <https://doi.org/10.6084/m9.figshare.c.6724251.v1> (version 1, posted 2024-04-23). Downloaded: `IRIS_event_set.zip` from <https://ndownloader.figshare.com/files/43809540> (item <https://doi.org/10.6084/m9.figshare.24894186.v1>) and `IRIS_event_set_README.txt` from <https://ndownloader.figshare.com/files/43809543> (item <https://doi.org/10.6084/m9.figshare.24894189.v1>). Data descriptor: <https://doi.org/10.1038/s41597-024-03250-y> | Raw tracks: no. `pixi run iris` in `packages/climada` fetches them into the git-ignored `data/iris/` and checks every file against `packages/climada/src/parametric_insurance_design_climada/iris_manifest.json` (MAR-72). Derived per-asset parity fixture: yes, `parity/tests/data/thesis_eventset/` (MAR-9) | Item records verified (MAR-9, re-checked MAR-72). Conflicting collection record found (MAR-72) | 2026-10-25 |
| STORM synthetic tropical cyclone tracks | Candidate second hazard catalogue (D7) | Its own terms | IBTrACS present-climate tracks: <https://doi.org/10.4121/12706085> | No | To verify: MAR-62 | — |
| IBTrACS | Input to CLIMADA synthetic tracks, the other D7 candidate | Its own terms | <https://www.ncei.noaa.gov/products/international-best-track-archive> | No | To verify: MAR-62 | — |
| CLIMADA LitPop exposure | Candidate open paper portfolio (D2 option b); CLIMADA tutorial | Its own terms | to verify | No | To verify: owning issue not yet filed | — |

### IRIS licence check (MAR-9)

Checked on 2026-10-25 for MAR-9, before committing the thesis parity fixture.

- **Primary source.** Sparks and Toumi's IRIS dataset is hosted on Springer Nature figshare as the collection "IRIS: The Imperial College Storm Model", <https://doi.org/10.6084/m9.figshare.c.6724251.v1> (version 1, posted 2024-04-23). It holds two items, each with its own licence field:
  - "Main dataset" (`IRIS_event_set.zip`), <https://doi.org/10.6084/m9.figshare.24894186.v1>: licence **CC0** (<https://creativecommons.org/publicdomain/zero/1.0/>).
  - "File descriptor" (`IRIS_event_set_README.txt`), <https://doi.org/10.6084/m9.figshare.24894189.v1>: licence **CC0**.
- **How it was read.** The figshare HTML pages refused automated access (HTTP 403), so the licence fields were read from figshare's public API records of the same items: <https://api.figshare.com/v2/articles/24894186> and <https://api.figshare.com/v2/articles/24894189>. The collection record (<https://api.figshare.com/v2/collections/6724251>) carries no licence of its own.
- **The article.** The data descriptor (Sparks, N. and Toumi, R., *Scientific Data* 11, 2024, <https://doi.org/10.1038/s41597-024-03250-y>; read at <https://pmc.ncbi.nlm.nih.gov/articles/PMC11043368/>) is under CC BY 4.0. Its Data Records section points to the figshare collection above. That licence covers the article, not the dataset.
- **Result.** CC0 places no restriction on redistributing the data or works derived from it, so the derived per-asset losses may be committed and published. The parity fixture is committed under `parity/tests/data/thesis_eventset/`, and its `metadata.json` records the licence as `CC0-1.0`, following the rule above that derived data keeps the source's terms.
- **Attribution.** CC0 doesn't require attribution, but scientific practice does: cite the data descriptor and the figshare collection wherever IRIS-derived data or results appear.
- **Scope.** This covers the IRIS event set only. The raw IRIS tracks are still not committed (size; they are fetched by the CLIMADA adapter, MAR-19). The derived losses were computed with CLIMADA, whose code is GPL-3.0. The GPL covers CLIMADA's code, not its numeric output: CLIMADA's own documentation states no terms for results, and the GNU GPL FAQ says output inherits the status of its input (<https://www.gnu.org/licenses/gpl-faq.html#GPLOutput>, read 2026-10-25). Confirmed by the owner on 2026-10-25 (MAR-79, ADR 0001 amendment 1). The asset portfolio is the owner's own.

#### Re-check: the item and collection records differ (MAR-72)

Checked on 2026-10-25 for MAR-72, when the download script was written. The D7 note (MAR-62, `research/notes/d7-second-hazard-catalogue.md`) records IRIS as CC BY 4.0 from the collection's DataCite record, which disagrees with the MAR-9 result above. Every record was read again from its API:

| Record | URL read | Licence it states |
|---|---|---|
| figshare item "Main dataset" (`IRIS_event_set.zip`, the file we download) | <https://api.figshare.com/v2/articles/24894186> | CC0 (<https://creativecommons.org/publicdomain/zero/1.0/>) |
| figshare item "File descriptor" (`IRIS_event_set_README.txt`, also downloaded) | <https://api.figshare.com/v2/articles/24894189> | CC0 |
| DataCite record of the "Main dataset" item | <https://api.datacite.org/dois/10.6084/m9.figshare.24894186.v1> (and the unversioned DOI) | `cc0-1.0` (Creative Commons Zero v1.0 Universal) |
| DataCite record of the "File descriptor" item | <https://api.datacite.org/dois/10.6084/m9.figshare.24894189.v1> | `cc0-1.0` |
| figshare collection "IRIS: The Imperial College Storm Model" | <https://api.figshare.com/v2/collections/6724251> | No licence field |
| DataCite record of the collection | <https://api.datacite.org/dois/10.6084/m9.figshare.c.6724251.v1> (and the unversioned DOI `10.6084/m9.figshare.c.6724251`) | `cc-by-4.0` (Creative Commons Attribution 4.0 International) |
| The data descriptor article | <https://pmc.ncbi.nlm.nih.gov/articles/PMC11043368/> | The article is CC BY 4.0. Its Data Records, Usage Notes and Code availability sections state no licence for the dataset |

- **Observation.** The records genuinely differ. Both items, the only files in the collection and the ones the script downloads, are CC0 in figshare and in DataCite. The collection's DataCite record is CC BY 4.0. figshare's own collection record has no licence field. No record says which one governs, and this check does not choose.
- **What reads differently.** Both licences allow redistributing the data and derived results. CC BY 4.0 would add binding conditions (credit, a link to the licence, and an indication of changes) that CC0 does not. The parity fixture's `metadata.json` records `CC0-1.0` (MAR-9).
- **Not reachable.** The figshare HTML pages for the collection did not serve automated requests (HTTP 202 with an empty body), so the human-readable pages were not read.
- **Open.** Which record governs is for the owner to decide. The download manifest records both (`iris_manifest.json`, `licence`). Citing the data descriptor and the collection, as the "Attribution" point above already asks, gives the credit CC BY 4.0 asks for; a link to the licence and a note of changes would also be needed if CC BY 4.0 governs.

## How to add or update a source

1. Add a row before the data is first downloaded or used.
2. Read the licence on the primary source (the provider's own page, not a mirror or a paper citing it). Write it down, with the URL and the date.
3. Record anything that limits use: non-commercial clauses, attribution text, redistribution, and whether derived results may be published.
4. If the terms are unclear or restrictive, escalate to the orchestrator before using the data.
