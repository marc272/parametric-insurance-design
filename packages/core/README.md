# parametric-insurance-design

The core library of [parametric-insurance-design](https://github.com/marc272/parametric-insurance-design): designing parametric insurance payout functions, per asset or across a portfolio.

```python
import parametric_insurance_design as pid
```

Status: pre-alpha. The package is a skeleton; the modules listed in `docs/SPEC.md` §4.2 are being built.

- Python 3.11 to 3.13, numpy ≥ 1.26, pandas ≥ 2.1.
- No hazard-model dependency. Hazard sources come in through the adapter packages, as EventSet files.
- Licence: BSD-3-Clause.
