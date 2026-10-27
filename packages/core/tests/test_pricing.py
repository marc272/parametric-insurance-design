"""PurePremium on hand-computed payouts (MAR-13, SPEC §6.4).

Doubles and context builder from ``_doubles.py`` (MAR-87): one entity, scale
1, a free payout per row. Rows: ``L = (0, 2, 4, 10)``, ``p = (0.4, 0.3, 0.2,
0.1)``.
"""

from __future__ import annotations

import numpy as np
import pytest
from numpy.typing import ArrayLike, NDArray

from parametric_insurance_design.errors import InputMismatchError
from parametric_insurance_design.interfaces import ProblemContext
from parametric_insurance_design.pricing import PurePremium

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
