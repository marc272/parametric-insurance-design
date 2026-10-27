# parametric-insurance-design

A Python library for designing parametric insurance payout functions. Given an event set of hazard-index values and losses (for example, wind speed and damage at each insured asset), it calibrates how much a policy pays as a function of the index. The payout is found by solving a linear program: the objective can be a weighted conditional value-at-risk (expected shortfall) of the uncovered loss, i.e. the loss left after the payout, or simpler measures such as the mean squared error, under a premium budget. Payouts can be calibrated per asset, per cluster of assets, or jointly across a portfolio. The library reworks the code of a master's thesis into a tested, installable package, with adapters for CLIMADA and Climate Risk Commons data.

**Status: pre-alpha.** The repository has just been set up and the packages are skeletons. The design is in [`docs/SPEC.md`](docs/SPEC.md).

## Repository layout

```
parametric-insurance-design/
├── packages/
│   ├── core/       # parametric-insurance-design: the core library, no hazard-model dependency
│   ├── viz/        # parametric-insurance-design-viz: figures, read from the result store
│   ├── crc/        # parametric-insurance-design-crc: Climate Risk Commons and VELO/CDT adapter (Python ≥ 3.12)
│   └── climada/    # parametric-insurance-design-climada: CLIMADA adapter (own pixi env, not a uv member)
├── research/       # paper: configs, run scripts, figure scripts, manuscript
├── showcase/crc/   # Climate Risk Commons showcase: notebook, pipeline, report
├── site/           # static website, reading exported bundles
├── parity/         # thesis golden data and parity tests
└── docs/           # SPEC.md, ADRs, data sources, runbooks
```

| Distribution | Import name |
|---|---|
| `parametric-insurance-design` | `parametric_insurance_design` (by convention `import parametric_insurance_design as pid`) |
| `parametric-insurance-design-viz` | `parametric_insurance_design_viz` |
| `parametric-insurance-design-crc` | `parametric_insurance_design_crc` |
| `parametric-insurance-design-climada` | `parametric_insurance_design_climada` |

## Environments

- **uv workspace** for `core`, `viz` and `crc`, with one lockfile (`uv.lock`). The core supports Python 3.11 to 3.13 with numpy ≥ 1.26 and pandas ≥ 2.1. The CRC adapter needs Python ≥ 3.12, so the workspace environment uses Python 3.12 or later (`.python-version` selects 3.12). CI also tests the core alone on Python 3.11, including with its lowest supported numpy and pandas.
- **pixi** for `packages/climada`, which is not a uv workspace member: CLIMADA comes from conda-forge, and its numpy pin would clash with the CRC adapter's requirements. That environment is not set up yet; the CLIMADA adapter work adds it.

The environments share data only through EventSet Parquet files (`docs/SPEC.md` §4.1, §5).

## Quickstart

Install [uv](https://docs.astral.sh/uv/), then, from a clone of this repository:

```bash
uv sync                          # create .venv with all workspace packages and the dev tools
uv run pytest                    # run the tests
uv run ruff check                # lint
uv run ruff format               # format
uv run pyright                   # type-check (basic mode)
uv run pre-commit install        # run the hooks on every commit
```

CI (GitHub Actions) runs ruff, pyright, the pre-commit hooks, the tests on Python 3.11, 3.12 and 3.13, a coverage gate of 85 % for the core, and a build of all four packages. See [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

## Licences

The licence boundary is the package boundary ([ADR 0001](docs/adr/0001-name-and-licence.md)):

| Part | Licence | Licence file |
|---|---|---|
| `packages/core`, `packages/viz` | BSD-3-Clause | [`LICENSE`](LICENSE) (copied into each package) |
| `research/`, `site/`, `docs/`, repository tooling | BSD-3-Clause | [`LICENSE`](LICENSE) |
| `parity/` code | BSD-3-Clause | [`parity/LICENSE`](parity/LICENSE) |
| `parity/golden/` (the thesis result tables) | CC0-1.0 | [`parity/golden/LICENSE`](parity/golden/LICENSE) |
| `parity/tests/data/thesis_eventset/` (derived from IRIS) | CC-BY-4.0: IRIS-derived data is treated as CC BY 4.0, the stricter of its two licence records (MAR-94) | recorded in its `metadata.json` |
| `showcase/crc/` code | BSD-3-Clause; the AGPL applies to the combined work with the CRC adapter | [`showcase/crc/LICENSE`](showcase/crc/LICENSE) |
| `packages/crc` | AGPL-3.0-or-later, because it imports the AGPL-licensed CRC SDK | [`packages/crc/LICENSE`](packages/crc/LICENSE) |
| `packages/climada` | GPL-3.0-or-later, because it imports GPLv3 CLIMADA | [`packages/climada/LICENSE`](packages/climada/LICENSE) |

The core and viz packages never import an adapter, so they stay under the permissive licence. Data comes with its own terms, recorded in [`docs/data-sources.md`](docs/data-sources.md). The only data committed are small fixtures: the CC BY 4.0 parity fixture, the CC0 thesis results in `parity/golden/`, and the CC BY 4.0 Florida tables of the paper portfolio in `research/data/` (D2).

## Thesis code

This project succeeds the code of the master's thesis, [marc272/parametric-insurance-framework](https://github.com/marc272/parametric-insurance-framework). That repository will be tagged `thesis-v1` and archived read-only; the new core is checked against it for parity before any method changes.

## Contributing

- [`docs/SPEC.md`](docs/SPEC.md): the technical spec (method, architecture, data contract, standards).
- [`AGENTS.md`](AGENTS.md): the working agreement for everyone who contributes, including AI agents.
- [`docs/adr/`](docs/adr/): architecture decision records.
- [`.github/pull_request_template.md`](.github/pull_request_template.md): what every pull request states.
