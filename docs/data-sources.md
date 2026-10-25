# Data sources

The data this project uses, and the terms each comes with. Data licences are separate from code licences (ADR 0001).

## Rules

- **No data is committed**, except small test fixtures. Downloads go through scripts that check checksums (`AGENTS.md`, `docs/SPEC.md` §4.3).
- Every EventSet records its source and licence in `metadata.json` (`docs/SPEC.md` §5).
- Data derived from a source keeps that source's terms, unless the source says otherwise.
- **Never guess a licence.** An entry is "verified" only when its licence was read from the primary source; record the date and the URL you read it from. Until then it stays "to verify", with the issue that will verify it.

## Sources

Started on 2026-10-25 (MAR-6) from what `docs/SPEC.md` and ADR 0001 state. No licence has been verified from its primary source yet, so the "Checked" column is empty. The source URLs were checked to resolve on 2026-10-25; they do not establish the licence.

| Source | Used for | Licence / terms | Source URL | Committed to the repo | Status | Checked |
|---|---|---|---|---|---|---|
| Climate Risk Commons (CRC) Open data | CRC showcase (`packages/crc`, `showcase/crc/`) | CC BY-NC 4.0, unless covered by the owner's agreement (as stated in ADR 0001) | to verify | No | To verify from the primary source: MAR-41 | — |
| VELO/CDT asset database | CRC showcase; candidate paper portfolio (D2) | The owner's licence (SPEC §1). Never committed | Licensed access only | Never | Terms to verify: MAR-41 | — |
| IRIS (Imperial College Storm Model) synthetic tropical cyclone event set | Hazard catalogue for the CLIMADA adapter and the thesis parity data | Its own terms | Data descriptor: <https://doi.org/10.1038/s41597-024-03250-y> | No | To verify: CLIMADA adapter, MAR-19 | — |
| STORM synthetic tropical cyclone tracks | Candidate second hazard catalogue (D7) | Its own terms | IBTrACS present-climate tracks: <https://doi.org/10.4121/12706085> | No | To verify: MAR-62 | — |
| IBTrACS | Input to CLIMADA synthetic tracks, the other D7 candidate | Its own terms | <https://www.ncei.noaa.gov/products/international-best-track-archive> | No | To verify: MAR-62 | — |
| CLIMADA LitPop exposure | Candidate open paper portfolio (D2 option b); CLIMADA tutorial | Its own terms | to verify | No | To verify: owning issue not yet filed | — |

## How to add or update a source

1. Add a row before the data is first downloaded or used.
2. Read the licence on the primary source (the provider's own page, not a mirror or a paper citing it). Write it down, with the URL and the date.
3. Record anything that limits use: non-commercial clauses, attribution text, redistribution, and whether derived results may be published.
4. If the terms are unclear or restrictive, escalate to the orchestrator before using the data.
