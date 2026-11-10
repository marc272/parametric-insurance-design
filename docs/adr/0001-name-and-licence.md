# ADR 0001: Project name and licences

- Status: Accepted
- Date: 2026-10-25
- Decision issues: MAR-5 (D1 name, D3 licence)
- Amendments: 1 (2026-10-25, MAR-79), 2 (2026-11-06, MAR-251), 3 (2026-11-06, MAR-273) and 4 (2026-11-10, MAR-310), at the end

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
| `research/`, `site/`, `docs/`, repo tooling | BSD 3-Clause | `BSD-3-Clause` |
| `examples/` | BSD 3-Clause, under the root `LICENSE` (ADR 0004, Q6) | `BSD-3-Clause` |
| `parity/` code (scripts, tests) | BSD 3-Clause (amendment 1) | `BSD-3-Clause` |
| `showcase/crc/` code (notebook, pipeline) | BSD 3-Clause (amendment 1) | `BSD-3-Clause` |
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

## Amendment 1 (2026-10-25, MAR-79): `parity/` and `showcase/crc/`

Decided by the owner, Marc Prinzing, on 2026-10-25 (recorded on MAR-79).

- **`parity/` code** (scripts and tests) is **BSD-3-Clause**, like the core it tests. `parity/LICENSE` is a copy of the root licence.
- **The derived parity fixture** (`parity/tests/data/thesis_eventset/`) is **CC-BY-4.0**, by the owner's decision of 2026-10-27 (MAR-94). This amendment first recorded CC0-1.0, following the IRIS figshare item records. The MAR-72 re-check found that the IRIS records differ: the figshare items say CC0 1.0, the collection's DataCite record says CC BY 4.0 (`docs/data-sources.md`, IRIS check). The owner decided that IRIS-derived data is treated as CC BY 4.0, the stricter of the two, so the fixture's `metadata.json` records `CC-BY-4.0`, and so does every EventSet the CLIMADA adapter builds from IRIS.
- **The thesis result tables** in `parity/golden/` (the thesis optimisation results and KPIs, the tables derived from the thesis code, and the simulation sweeps regenerated with it) are **CC-BY-4.0**, by the owner's revised decision of 2026-10-27 (MAR-94; applied in MAR-135). They were computed from IRIS-derived losses, which are treated as CC BY 4.0. This revision supersedes the CC0-1.0 that the same decision first recorded for them (applied in MAR-109). `parity/golden/LICENSE` states the licence and the attribution to give.
- **CLIMADA's GPL-3.0 and its output.** The fixture's losses were computed with CLIMADA, which is GPL-3.0. CLIMADA's documentation states the GPL for the software and nothing about results; the GNU GPL FAQ says the output of a program is not, in general, covered by the copyright on its code, and that output inherits the copyright status of the input it was generated from (<https://www.gnu.org/licenses/gpl-faq.html#WhatCaseIsOutputGPL>, <https://www.gnu.org/licenses/gpl-faq.html#GPLOutput>, read 2026-10-25). The input here is IRIS (treated as CC BY 4.0, above) plus the owner's own asset portfolio, so the GPL does not attach to the fixture. Code that imports CLIMADA stays GPL (`packages/climada`).
- **`showcase/crc/` code** (notebook and pipeline) is **BSD-3-Clause**. It runs on the AGPL-3.0-or-later CRC adapter and SDK, so the AGPL applies to the combined work when it is distributed or served over a network; the showcase's own source stays permissive. `showcase/crc/LICENSE` is a copy of the root licence.
- **Unchanged:** CRC Open data remains CC BY-NC 4.0 unless the owner's agreement says otherwise (MAR-41); data licences are recorded in `docs/data-sources.md`.

## Amendment 2 (2026-11-06, MAR-251): `showcase/crc/` and `packages/crc` after D9

On 2026-11-05 the owner decided D9 (`docs/SPEC.md` §11; MAR-242). The CRC work is now a parametric insurance module in crc-sdk, `crc_sdk.parametric`, with a showcase notebook in crc-docs. Both are built in the forks `marc272/crc-sdk` and `marc272/crc-docs` and contributed upstream. The module plan is in `docs/SPEC.md` §8. This amendment records what D9 means for this ADR. It changes no licence.

- **`showcase/crc/` is no longer a planned output.** No notebook or pipeline was written there, and none is planned. The folder holds the record of the CRC collaboration scan and the meeting brief (`showcase/crc/README.md`), BSD-3-Clause under `showcase/crc/LICENSE`. The table's row "`showcase/crc/` code (notebook, pipeline)" and amendment 1's bullet on it are kept as history.
- **The CRC module** is part of crc-sdk, outside this repository, so the table above doesn't list it. It takes crc-sdk's licence, AGPL-3.0-or-later (D3). It never imports this repository's core: parity is checked through golden fixtures that the core exports (MAR-245).
- **The notebook** is built in the crc-docs fork. Its terms are the owner's (2026-11-05), not this ADR's.
- **`packages/crc` is dormant.** It holds no adapter code, and no work is planned in it (`docs/SPEC.md` §4, `packages/crc/README.md`). It keeps AGPL-3.0-or-later, and the rule above still applies to it. Whether it stays dormant or is removed is open (MAR-252).
- **Unchanged:** the table's other rows. CRC Open data remains CC BY-NC 4.0 unless the owner's agreement says otherwise, and no CRC data is committed (`docs/data-sources.md`).

## Amendment 3 (2026-11-06, MAR-273): the CRC golden fixtures

Decided by the owner, Marc Prinzing, on 2026-11-06 (recorded on MAR-245; applied in MAR-273).

The golden fixtures of the CRC module are JSON cases in `parity/crc/cases/` (MAR-245). The BSD-3-Clause export script `parity/scripts/export_crc_fixtures.py` generates them with the core, and the module's tests in the crc-sdk fork read copies of them. This amendment records their licence.

- **A case follows its data set.** A case's licence is that of its data set, the last part of its case id before any suffix. The case files carry no licence field. The licence table in `parity/crc/README.md` ("Licence") is their marker: it names the case ids of each data set and gives the licence and the attribution.
- **`synthetic`, `synthetic52` and `handmade`: CC0-1.0**, the fresh draws of the `-fresh` cases included. The owner dedicates these cases to the public domain under CC0 1.0 Universal. They hold no third-party data: their draws come from the script's seeded generator or were chosen by hand. The decision names "synthetic and handmade". `synthetic52` is a synthetic data set of the same generator (asset A1 of `synthetic` in its first 52 years), and the fresh draws come from that generator too, so both are covered. MAR-273 states this reading.
- **`thesis`: CC-BY-4.0**, with the IRIS attribution. These cases hold draws of the parity fixture `parity/tests/data/thesis_eventset/`, which is IRIS-derived and CC-BY-4.0 (amendment 1, MAR-94). The attribution that a copy keeps is in `parity/crc/README.md`.
- **Copies keep their case's licence.** The crc-sdk fork (AGPL-3.0-or-later) copies cases into `tests/fixtures/parametric/cases/`. Each copy keeps CC0-1.0 or CC-BY-4.0 by its data set, and the `thesis` copies keep the attribution. The fork's `tests/fixtures/parametric/README.md` states these terms. The same holds for any further copy.
- **Unchanged:** the table's rows and amendments 1 and 2. The export script and its test stay BSD-3-Clause, like the rest of the `parity/` code (`parity/LICENSE`, amendment 1).

## Amendment 4 (2026-11-10, MAR-310): the CLIMADA golden fixtures

Decided by the owner, Marc Prinzing, on 2026-11-10, by accepting ADR 0006 (D12, MAR-48), whose §12 sets the licence. Applied in K-13 (MAR-312) and recorded here in K-11 (MAR-310).

The golden fixtures of the CLIMADA module `climada_petals.engine.parametric` are the JSON samples and cases in `parity/climada/` (MAR-312). The export script `parity/scripts/export_climada_fixtures.py` generates them with the core, and K-18 and K-19 copy them into the module's test data in the fork `marc272/climada_petals`, which is GPL v3. This amendment records their licence.

- **The script and its test, `parity/tests/test_climada_fixtures.py`: BSD-3-Clause**, like the rest of the `parity/` code (`parity/LICENSE`, amendment 1).
- **The samples in `parity/climada/samples/` and the cases in `parity/climada/cases/`: CC0-1.0.** The owner dedicates them to the public domain under CC0 1.0 Universal, by accepting ADR 0006 on 2026-11-10. They hold no third-party data: every sample comes from the script's seeded generator or was chosen by hand. Every sample records `"licence": "CC0-1.0"`, and `parity/climada/README.md` ("Licence"), `parity/README.md` and `docs/data-sources.md` record it too.
- **Copies in the fork.** CC0 is compatible with GPL v3, so the copies carry no attribution duty. Unlike the CRC cases of amendment 3, no case here follows a third-party data set.
- **Unchanged:** the table's rows and amendments 1 to 3.
