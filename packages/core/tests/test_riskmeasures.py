"""``riskmeasures``: VaR, CVaR and lower quantiles on a step (MAR-143).

``var_cvar``'s formulas are tested in ``test_evaluate.py`` (MAR-16), through
the re-export in ``evaluate``. These tests cover what MAR-143 changed: the
module boundary (pricing no longer imports evaluate) and the tolerance at a
step of the distribution, which makes the VaR independent of the order in
which tied values are summed.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from parametric_insurance_design import evaluate, pricing, riskmeasures
from parametric_insurance_design.errors import ComponentConfigError
from parametric_insurance_design.riskmeasures import (
    CDF_ATOL,
    check_beta,
    discrete_distribution,
    lower_quantile,
    sorted_cdf,
    var_cvar,
)


def imported_modules(module: object) -> set[str]:
    """Modules a source file imports (``import x``, ``from x import y``)."""
    path = Path(getattr(module, "__file__", ""))
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            out.add(node.module)
    return out


def test_pricing_does_not_import_evaluate() -> None:
    assert "parametric_insurance_design.evaluate" not in imported_modules(pricing)
    assert "parametric_insurance_design.riskmeasures" in imported_modules(pricing)


def test_riskmeasures_imports_no_problem_or_evaluation_module() -> None:
    package = {m for m in imported_modules(riskmeasures) if m.startswith("parametric_")}
    assert package == {
        "parametric_insurance_design.basis",
        "parametric_insurance_design.errors",
    }


def test_evaluate_re_exports_var_cvar() -> None:
    assert evaluate.var_cvar is var_cvar
    assert "var_cvar" in evaluate.__all__


def test_var_cvar_is_the_lower_quantile_and_the_tail_mean() -> None:
    assert var_cvar([0.0, 1.0, 2.0, 10.0], [0.25] * 4, 0.5) == (1.0, 6.0)
    x, p = discrete_distribution([3.0, 1.0, 2.0], [0.2, 0.5, 0.3])
    sorted_x, sorted_p, cdf = sorted_cdf(x, p)
    np.testing.assert_array_equal(sorted_x, [1.0, 2.0, 3.0])
    np.testing.assert_array_equal(sorted_p, [0.5, 0.3, 0.2])
    assert lower_quantile(sorted_x, cdf, 0.5) == 1.0
    assert lower_quantile(sorted_x, cdf, 0.81) == 3.0
    assert check_beta(0.9) == 0.9
    with pytest.raises(ComponentConfigError):
        check_beta(1.0)


@pytest.mark.parametrize("offset", [-5e-11, -1e-15, 0.0, 1e-15])
def test_a_level_within_the_tolerance_of_a_step_reaches_it(offset: float) -> None:
    # Ten equally likely values: P(X <= 6) = 0.7. A level a rounding error
    # either side of 0.7 is the step itself: the VaR is 6 (exact arithmetic).
    values = np.arange(10.0)
    prob = np.full(10, 0.1)
    var, cvar = var_cvar(values, prob, 0.7 + offset)
    assert var == 6.0
    assert cvar == pytest.approx(8.0, rel=1e-9)  # mean of 7, 8, 9


def test_a_level_beyond_the_tolerance_is_not_a_step() -> None:
    values = np.arange(10.0)
    prob = np.full(10, 0.1)
    assert var_cvar(values, prob, 0.7 + 10 * CDF_ATOL)[0] == 7.0
    assert var_cvar(values, prob, 0.7 - 10 * CDF_ATOL)[0] == 6.0
    # Far from the step: the next value up.
    assert var_cvar(values, prob, 0.75)[0] == 7.0


def test_var_does_not_depend_on_the_order_of_tied_values() -> None:
    # 40 equally likely outcomes with many ties and beta = 0.8, on a step:
    # whichever order argsort puts the ties in (it differs between Linux and
    # macOS), the VaR is the same atom.
    rng = np.random.default_rng(143)
    values = rng.integers(0, 6, size=40).astype(np.float64)
    prob = np.full(40, 1 / 40)
    beta = 0.8
    reference = var_cvar(values, prob, beta)
    sorted_values = np.sort(values)
    # The exact-arithmetic quantile: the 32nd smallest value (32 / 40 = 0.8).
    assert reference[0] == sorted_values[31]
    for _ in range(50):
        perm = rng.permutation(40)
        var, cvar = var_cvar(values[perm], prob[perm], beta)
        assert var == reference[0]
        assert cvar == pytest.approx(reference[1], rel=1e-12)


def test_var_on_a_step_under_unequal_probabilities() -> None:
    # Cumulative sums 0.1 + 0.2 = 0.30000000000000004 and the like: the
    # level 0.3 is reached by the second value, as in exact arithmetic.
    values = np.array([1.0, 2.0, 3.0, 4.0])
    prob = np.array([0.1, 0.2, 0.3, 0.4])
    assert var_cvar(values, prob, 0.3)[0] == 2.0
    assert var_cvar(values, prob, 0.6)[0] == 3.0
