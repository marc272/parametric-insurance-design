# parametric-insurance-design-climada

Adapter from CLIMADA to the EventSet of [parametric-insurance-design](https://github.com/marc272/parametric-insurance-design): tracks → CLIMADA hazard and impact → EventSet.

```python
import parametric_insurance_design_climada
```

Status: skeleton, with its environment and CI. The adapter itself comes with the CLIMADA adapter work (Linear MAR-19 and its sub-issues).

## Environment

This package is **not a member of the uv workspace**. CLIMADA comes from conda-forge, and its pins would clash with the CRC adapter's pandas ≥ 3 requirement, so this package has its own **pixi** environment (`docs/SPEC.md` §4.1):

- `pixi.toml` and the committed `pixi.lock` in this folder define it: CLIMADA 6.1.0 on Python 3.12 from conda-forge, the core installed editable from `../core`, and this package installed editable from `.`.
- The core's dependencies come from conda-forge too, so no PyPI wheel shadows the conda numpy/scipy stack.
- Locked platforms: `linux-64` (CI) and `osx-arm64`. Add one with `pixi workspace platform add <platform>`.

From this folder:

```sh
pixi run test        # this package's tests
pixi run test-core   # the core's tests, in this env
pixi lock            # after changing pixi.toml, pyproject.toml or the core's dependencies; commit pixi.lock
```

CI runs both test tasks in the workflow `.github/workflows/climada.yml` with `pixi install --locked`, so it fails when `pixi.lock` is out of date, including after a change to the core's dependencies.

## Rules

- It never imports `parametric_insurance_design_crc`, and the env does not contain it: the CLIMADA stream is CRC-free. A smoke test checks this.
- Licence: GPL-3.0-or-later, because it imports GPLv3 CLIMADA (ADR 0001). See `LICENSE` in this folder.
