"""PurePremium (MAR-13) and CostOfCapitalLoad (MAR-27) on hand-computed
payouts (SPEC §6.4).

Doubles and context builder from ``_doubles.py`` (MAR-87): one entity, scale
1, a free payout per row. Rows: ``L = (0, 2, 4, 10)``, ``p = (0.4, 0.3, 0.2,
0.1)``.
"""

from __future__ import annotations

import numpy as np
import pytest
from numpy.typing import ArrayLike, NDArray

from parametric_insurance_design.errors import ComponentConfigError, InputMismatchError
from parametric_insurance_design.interfaces import ProblemContext
from parametric_insurance_design.pricing import CostOfCapitalLoad, PurePremium

from ._doubles import FreePayout, event_measure, grouped_measure, make_context

PAYOUT = np.array([1.0, 1.0, 1.0, 4.0])
# 0.4 + 0.3 + 0.2 + 0.4
PREMIUM = 1.3


def premium_at(ctx: ProblemContext, payout: ArrayLike) -> float:
    term = PurePremium().premium(ctx)
    ctx.theta.value = np.asarray(payout, dtype=np.float64)[None, :]
    v = term.expression.value
    assert v is not None
    return float(np.asarray(v))


def test_premium_is_the_expected_payout() -> None:
    ctx = make_context(FreePayout(), measure=event_measure())
    term = PurePremium().premium(ctx)
    assert term.constraints == ()
    assert term.expression.is_affine()
    assert premium_at(ctx, PAYOUT) == pytest.approx(PREMIUM, rel=1e-12)


def test_premium_value_matches_the_expression() -> None:
    measure = event_measure()
    assert PurePremium().premium_value(PAYOUT, measure) == pytest.approx(
        PREMIUM, rel=1e-12
    )
    assert PurePremium().premium_value(PAYOUT.tolist(), measure) == pytest.approx(
        premium_at(make_context(FreePayout(), measure=measure), PAYOUT), rel=1e-12
    )


def test_premium_of_zero_payout_is_zero() -> None:
    ctx = make_context(FreePayout(), measure=event_measure())
    assert premium_at(ctx, np.zeros(4)) == 0.0
    assert PurePremium().premium_value(np.zeros(4), ctx.measure) == 0.0


def test_premium_aggregates_rows_into_outcomes() -> None:
    # Outcome payouts (1 + 1, 1, 4, 0), probability 1/4 each.
    measure = grouped_measure()
    expected = (2 + 1 + 4 + 0) / 4
    ctx = make_context(FreePayout(), measure=measure)
    assert premium_at(ctx, PAYOUT) == pytest.approx(expected)
    assert PurePremium().premium_value(PAYOUT, measure) == pytest.approx(expected)


def test_premium_is_homogeneous_of_degree_one() -> None:
    ctx = make_context(FreePayout(), measure=event_measure())
    assert premium_at(ctx, 3.0 * PAYOUT) == pytest.approx(3.0 * PREMIUM)


@pytest.mark.parametrize(
    ("payout", "match"),
    [
        (np.ones(3), "shape"),
        (np.ones((4, 1)), "shape"),
        (np.array([1.0, np.nan, 1.0, 1.0]), "finite"),
        (np.array([1.0, np.inf, 1.0, 1.0]), "finite"),
    ],
)
def test_premium_value_rejects_bad_payouts(
    payout: NDArray[np.float64], match: str
) -> None:
    with pytest.raises(InputMismatchError, match=match):
        PurePremium().premium_value(payout, event_measure())


def test_name() -> None:
    assert PurePremium.name == "pure"
    assert PurePremium() == PurePremium()


# --- CostOfCapitalLoad (MAR-27) ----------------------------------------------
# PAYOUT = (1, 1, 1, 4) with p = (0.4, 0.3, 0.2, 0.1): E[pi] = 1.3.
# CVaR_q(pi) is the mean of the worst 1 - q probability mass:
#   q = 0.5:  (0.1 * 4 + 0.4 * 1) / 0.5 = 1.6
#   q = 0.8:  (0.1 * 4 + 0.1 * 1) / 0.2 = 2.5
#   q = 0.95: 4 (the worst 5 % lies in the row paying 4)
PAYOUT_CVAR = {0.5: 1.6, 0.8: 2.5, 0.95: 4.0}


def loaded_premium_at(
    pricing: CostOfCapitalLoad, ctx: ProblemContext, payout: ArrayLike
) -> float:
    term = pricing.premium(ctx)
    ctx.theta.value = np.asarray(payout, dtype=np.float64)[None, :]
    v = term.expression.value
    assert v is not None
    return float(np.asarray(v))


@pytest.mark.parametrize("q", sorted(PAYOUT_CVAR))
@pytest.mark.parametrize("rate", [0.06, 0.1, 0.5, 1.0])
def test_loaded_premium_matches_hand_computed_values(rate: float, q: float) -> None:
    pricing = CostOfCapitalLoad(rate=rate, q=q)
    expected = (1 - rate) * PREMIUM + rate * PAYOUT_CVAR[q]
    measure = event_measure()
    assert pricing.premium_value(PAYOUT, measure) == pytest.approx(expected, rel=1e-12)
    ctx = make_context(FreePayout(), measure=measure)
    # The expression's value solves the inner Rockafellar-Uryasev LP.
    assert loaded_premium_at(pricing, ctx, PAYOUT) == pytest.approx(expected, rel=1e-7)


def test_rate_zero_is_the_pure_premium() -> None:
    """r = 0 reduces to the pure premium: same term, same value, bit for bit."""
    measure = event_measure()
    loaded = CostOfCapitalLoad(rate=0.0, q=0.99)
    assert loaded.premium_value(PAYOUT, measure) == PurePremium().premium_value(
        PAYOUT, measure
    )
    ctx = make_context(FreePayout(), measure=measure)
    term = loaded.premium(ctx)
    assert term.constraints == ()
    assert term.expression.is_affine()
    assert loaded_premium_at(loaded, ctx, PAYOUT) == premium_at(ctx, PAYOUT)
    grouped = grouped_measure()
    assert loaded.premium_value(PAYOUT, grouped) == PurePremium().premium_value(
        PAYOUT, grouped
    )


def test_rate_one_is_the_payout_cvar() -> None:
    measure = event_measure()
    for q, cvar in PAYOUT_CVAR.items():
        assert CostOfCapitalLoad(rate=1.0, q=q).premium_value(
            PAYOUT, measure
        ) == pytest.approx(cvar, rel=1e-12)


def test_loaded_premium_is_convex_without_own_constraints() -> None:
    ctx = make_context(FreePayout(), measure=event_measure())
    term = CostOfCapitalLoad(rate=0.1, q=0.99).premium(ctx)
    assert term.constraints == ()
    assert term.expression.is_convex()
    assert not term.expression.is_affine()
    assert term.expression.is_dcp()


def test_loaded_premium_aggregates_rows_into_outcomes() -> None:
    # Real annual measure (MAR-24): years {0, 1}, {2}, {3} and an empty year.
    # Outcome payouts (1 + 1, 1, 4, 0), probability 1/4 each: E = 7/4 and
    # CVaR_0.5 = (4 + 2) / 2 = 3.
    measure = grouped_measure()
    pricing = CostOfCapitalLoad(rate=0.2, q=0.5)
    expected = 0.8 * 7 / 4 + 0.2 * 3
    assert pricing.premium_value(PAYOUT, measure) == pytest.approx(expected)
    ctx = make_context(FreePayout(), measure=measure)
    assert loaded_premium_at(pricing, ctx, PAYOUT) == pytest.approx(expected, rel=1e-7)


def test_loaded_premium_lies_between_mean_and_cvar_and_is_homogeneous() -> None:
    rng = np.random.default_rng(27)
    measure = event_measure()
    pure = PurePremium()
    for _ in range(20):
        payout = rng.uniform(0.0, 10.0, size=4)
        rate, q = float(rng.uniform(0, 1)), float(rng.uniform(0.05, 0.95))
        loaded = CostOfCapitalLoad(rate=rate, q=q)
        value = loaded.premium_value(payout, measure)
        cvar = CostOfCapitalLoad(rate=1.0, q=q).premium_value(payout, measure)
        assert pure.premium_value(payout, measure) <= value + 1e-12
        assert value <= cvar + 1e-12
        assert loaded.premium_value(2.5 * payout, measure) == pytest.approx(
            2.5 * value, rel=1e-12
        )
        ctx = make_context(FreePayout(), measure=measure)
        assert loaded_premium_at(loaded, ctx, payout) == pytest.approx(
            value, rel=1e-7, abs=1e-9
        )


def test_loaded_premium_value_is_none_before_a_solve() -> None:
    ctx = make_context(FreePayout(), measure=event_measure())
    term = CostOfCapitalLoad(rate=0.1, q=0.99).premium(ctx)
    assert term.expression.value is None


@pytest.mark.parametrize(
    ("payout", "match"),
    [
        (np.ones(3), "shape"),
        (np.ones((4, 1)), "shape"),
        (np.array([1.0, np.nan, 1.0, 1.0]), "finite"),
        (np.array([1.0, np.inf, 1.0, 1.0]), "finite"),
    ],
)
def test_loaded_premium_value_rejects_bad_payouts(
    payout: NDArray[np.float64], match: str
) -> None:
    for rate in (0.0, 0.1):
        with pytest.raises(InputMismatchError, match=match):
            CostOfCapitalLoad(rate=rate, q=0.99).premium_value(payout, event_measure())


@pytest.mark.parametrize(
    ("rate", "q", "match"),
    [
        (-0.01, 0.99, "rate must lie"),
        (1.01, 0.99, "rate must lie"),
        (float("nan"), 0.99, "rate must be finite"),
        (True, 0.99, "rate must be a real number"),
        ("0.1", 0.99, "rate must be a real number"),
        (0.1, 0.0, "q must lie"),
        (0.1, 1.0, "q must lie"),
        (0.1, float("inf"), "q must be finite"),
        (0.1, None, "q must be a real number"),
    ],
)
def test_cost_of_capital_rejects_bad_parameters(
    rate: object, q: object, match: str
) -> None:
    with pytest.raises(ComponentConfigError, match=match):
        CostOfCapitalLoad(rate=rate, q=q)  # type: ignore[arg-type]


def test_cost_of_capital_name_and_coercion() -> None:
    assert CostOfCapitalLoad.name == "cost_of_capital"
    pricing = CostOfCapitalLoad(rate=0, q=np.float64(0.99))
    assert isinstance(pricing.rate, float)
    assert pricing.rate == 0.0
    assert isinstance(pricing.q, float)
    assert pricing.q == 0.99
    assert CostOfCapitalLoad(0.1, 0.99) == CostOfCapitalLoad(rate=0.1, q=0.99)
