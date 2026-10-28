"""``riskmeasures``: VaR, CVaR and lower quantiles on a step (MAR-143).

``var_cvar``'s formulas are tested in ``test_evaluate.py`` (MAR-16), through
the re-export in ``evaluate``. These tests cover what MAR-143 changed: the
module boundary (pricing no longer imports evaluate), and they pin the
strict comparison at a step of the distribution, as in the thesis (MAR-143,
option B): the bootstrap's tolerance ``CDF_ATOL`` is not applied here.
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


def test_var_on_an_exact_step_is_strict_and_can_be_the_upper_atom() -> None:
    # Ten equally likely values 1..10 and beta = 0.8 exactly: P(X <= 8) = 0.8
    # in exact arithmetic, so the exact quantile is 8. The normalised
    # probabilities sum to a rounding error below 0.8 at 8, and the strict
    # comparison (thesis) returns the next atom up. No ties, so the summation
    # order, and this result, is the same on every platform.
    values = np.arange(1.0, 11.0)
    prob = np.full(10, 0.1)
    assert var_cvar(values, prob, 0.8) == (9.0, 9.5)
    assert var_cvar(values, prob, 0.9) == (10.0, 10.0)
    x, p = discrete_distribution(values, prob)
    sorted_x, _, cdf = sorted_cdf(x, p)
    assert cdf[7] < 0.8  # the rounding that moves the quantile up a step
    assert lower_quantile(sorted_x, cdf, 0.8) == 9.0
    # A tolerance (the bootstrap's) would give the exact-arithmetic atom.
    assert cdf[7] >= 0.8 - CDF_ATOL


def test_lower_quantile_ignores_cdf_atol() -> None:
    # beta a rounding error (5e-13, far inside CDF_ATOL) above the 0.7 step
    # of ten equally likely values: strict, so the next value up.
    values = np.arange(10.0)
    prob = np.full(10, 0.1)
    beta = float(np.cumsum(prob)[6]) + 5e-13
    assert 5e-13 < CDF_ATOL
    assert var_cvar(values, prob, beta)[0] == 7.0


def test_var_off_a_step_is_the_lower_quantile() -> None:
    values = np.arange(10.0)
    prob = np.full(10, 0.1)
    assert var_cvar(values, prob, 0.75)[0] == 7.0
    assert var_cvar(values, prob, 0.65)[0] == 6.0
