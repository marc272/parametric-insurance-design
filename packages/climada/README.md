# parametric-insurance-design-climada

Adapter from CLIMADA to the EventSet of [parametric-insurance-design](https://github.com/marc272/parametric-insurance-design): tracks → CLIMADA hazard and impact → EventSet.

```python
import parametric_insurance_design_climada
```

Status: skeleton only.

- **Not a member of the uv workspace.** CLIMADA comes from conda-forge, and its numpy pin would clash with the CRC adapter's pandas ≥ 3 requirement, so this package gets its own **pixi** environment, with the core installed as an editable path dependency (`docs/SPEC.md` §4.1).
- The pixi environment, the CLIMADA dependency and the lockfile do not exist yet. They are added by the CLIMADA adapter work (Linear MAR-19 and its sub-issues), which also adds this package's tests and CI.
- It never imports `parametric_insurance_design_crc`: the CLIMADA stream is CRC-free.
- Licence: GPL-3.0-or-later, because it will import GPLv3 CLIMADA (ADR 0001). See `LICENSE` in this folder.
