# parametric-insurance-design-crc

A dormant skeleton for an adapter from Climate Risk Commons (CRC) and VELO/CDT data to the EventSet of [parametric-insurance-design](https://github.com/marc272/parametric-insurance-design). It holds no adapter code: the package exports only its version.

The package is dormant since 2026-11-05. The program's CRC work is now a parametric insurance module inside the CRC SDK itself, `crc_sdk.parametric`, built in a fork of crc-sdk. That module's CRC data path lives in the module, so no work is planned here.

- Version 0.1.0.dev0, not released. Python ≥ 3.12. A member of the repository's uv workspace: install from a clone with `uv sync`.
- Licence: AGPL-3.0-or-later, because the package was set up to import the AGPL-licensed CRC SDK ([ADR 0001](https://github.com/marc272/parametric-insurance-design/blob/main/docs/adr/0001-name-and-licence.md)). See `LICENSE` in this folder.
- The core, the viz package and the CLIMADA adapter never import this package, so they keep their own licences.
- No CRC or VELO data is committed. Data terms are recorded in [`docs/data-sources.md`](https://github.com/marc272/parametric-insurance-design/blob/main/docs/data-sources.md).
- The repository's [README](https://github.com/marc272/parametric-insurance-design#readme) has the project's status and a quickstart.
