# ADR 0001: Project name and licences

- Status: Accepted
- Date: 2026-10-25
- Decision issues: MAR-5 (D1 name, D3 licence)

## Context

The thesis code is being reworked into a new monorepo with four distributions. The core library has no hazard-model dependency. Two adapters wrap copyleft libraries:

- CLIMADA (and climada-petals): GPLv3, per the CLIMADA website and PyPI metadata.
- `crc-sdk` and `crc-framework`: AGPL-3.0-or-later (PyPI license expression, checked 2026-10-25).

The core's direct dependencies are all permissive: numpy, scipy and pandas (BSD), cvxpy and pyarrow (Apache-2.0), pydantic (MIT), matplotlib (PSF-based).

Goals for the licence choice:

1. Researchers and practitioners, insurers included, can reuse the core freely.
2. The core can flow into GPL/AGPL code: the CLIMADA contribution and both adapters.
3. Every package respects the terms of the libraries it imports.

## Decision

**Name (D1):** repository and distribution `parametric-insurance-design`. The import package is `parametric_insurance_design`, and the docs alias is `pid`. Sub-distributions are `-viz`, `-crc` and `-climada`. All names were free on PyPI and GitHub on 2026-10-25.

**Licences (D3):** the licence boundary is the package boundary.

| Package | Licence | SPDX |
|---|---|---|
| `packages/core` | BSD 3-Clause | `BSD-3-Clause` |
| `packages/viz` | BSD 3-Clause | `BSD-3-Clause` |
| `research/`, `site/`, repo tooling | BSD 3-Clause | `BSD-3-Clause` |
| `packages/climada` | GNU GPL v3 or later | `GPL-3.0-or-later` |
| `packages/crc` | GNU AGPL v3 or later | `AGPL-3.0-or-later` |

Implementation:

- A root `LICENSE` file (BSD-3-Clause).
- `packages/climada/LICENSE` (GPL-3.0) and `packages/crc/LICENSE` (AGPL-3.0).
- An SPDX `license` field in each `pyproject.toml`.
- A README section explaining the split.

**Rule:** `core` and `viz` must never import `packages/climada` or `packages/crc`.

## Rationale

- **BSD-3-Clause for the core.**
  - It is the scientific Python convention, so the target audience knows it.
  - It is permissive, which matters for adoption by practitioners.
  - It is compatible with GPLv3 and AGPLv3, so the core can be used by the adapters and ported into CLIMADA.
  - The non-endorsement clause protects the project's and author's names.
- **Why not the alternatives:**
  - MIT would have worked equally well; BSD-3 was chosen for ecosystem fit.
  - Apache-2.0 adds an explicit patent grant, which is not worth the extra weight for a single-author research codebase.
- **GPL-3.0-or-later for the CLIMADA adapter.** It imports GPLv3 CLIMADA. "Or later" keeps compatibility whether upstream is v3-only or v3-or-later.
- **AGPL-3.0-or-later for the CRC adapter.** It imports AGPL-licensed crc-sdk and crc-framework.
- **The CLIMADA contribution** (Linear project "CLIMADA Contribution") goes upstream under CLIMADA's GPLv3. As copyright holder of the core, the owner can contribute ported code under those terms.

## Consequences

- Copyleft obligations stay inside the two adapter packages. Users who need only the core get a permissive licence.
- If the owner's agreement with Riskthinking.AI grants other terms for the CRC SDK, the CRC adapter's licence can be revisited. Record that in a new ADR.
- Data licences are separate from code licences: CRC Open data is CC BY-NC 4.0 unless covered by the owner's agreement, and IRIS/STORM carry their own terms. They are recorded in `docs/data-sources.md` and in EventSet metadata.
