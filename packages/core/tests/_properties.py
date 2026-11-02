"""Shared helpers of the engine and design property tests (MAR-177).

Imported by ``test_engine_properties.py``, ``test_engine_properties_bases.py``,
``test_engine_properties_loaded.py`` and ``test_design_properties.py`` with
``from ._properties import ...`` (a relative import works under
``--import-mode=importlib``, as for ``_doubles.py``). It holds what those
files had written out four times:

* the payout range, the solver tolerances and the hypothesis profile;
* the EventSet maker (event-major rows, one or more draws per event);
* the shared data strategies: :func:`eventsets` (one event per year,
  unequal rates) and :func:`layouts` (several events per year, draws);
* the component strategies;
* the independent numpy outcome measure of SPEC §6.2, written without
  ``basis.py``, and the SPEC §6 objectives evaluated on it.

``test_design_properties.py`` keeps its own ``layouts`` (zero-loss outcomes
and location values), and each file keeps its own result wrapper, which
differ in what they draw and record.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from numpy.typing import ArrayLike, NDArray

from parametric_insurance_design.basis import Basis
from parametric_insurance_design.constraints import Budget
from parametric_insurance_design.eventset import (
    EventSet,
    EventSetMetadata,
    HazardSource,
    IndexDefinition,
    LossDefinition,
    Provenance,
)
from parametric_insurance_design.interfaces import Objective, Scope, SolveResult
from parametric_insurance_design.objectives import (
    MSE,
    ExpectedUncovered,
    WeightedCVaR,
)
from parametric_insurance_design.payout import StepPayout
from parametric_insurance_design.riskmeasures import var_cvar
from parametric_insurance_design.scopes import Individual, Portfolio

ATTACHMENT = 20.0
LIMIT = 70.0

# --- Tolerances and the hypothesis profile ----------------------------------

TOL_INTERIOR_POINT = 1e-6
"""Tolerance in scaled units (losses divided by the problem's scale, so <= 1)
for interior-point solvers (Clarabel, HiGHS) and for OSQP with the default
policy's ``eps_abs = eps_rel = 1e-8`` (MAR-98): measured violations are about
3e-9 (Clarabel) and 1.2e-8 (OSQP) on these EventSets."""
TOL_FIRST_ORDER = 1e-4
"""Tolerance in scaled units for SCS (first-order, run at its default
accuracy). Real violations would be of the order of the losses themselves,
i.e. near 1."""
FIRST_ORDER_SOLVERS = frozenset({"SCS"})


def solver_tol(solvers: str | Sequence[SolveResult]) -> float:
    """Tolerance in scaled units for the least accurate solver used.

    Parameters
    ----------
    solvers : str or sequence of SolveResult
        One solver's name, or the results whose solvers count.
    """
    names = [solvers] if isinstance(solvers, str) else [r.solver for r in solvers]
    if any(name in FIRST_ORDER_SOLVERS for name in names):
        return TOL_FIRST_ORDER
    return TOL_INTERIOR_POINT


def homogeneity(objective: Objective) -> int:
    """Degree of the objective in the losses: 2 for MSE, else 1."""
    return 2 if isinstance(objective, MSE) else 1


PROPERTY_SETTINGS = settings(
    derandomize=True,
    database=None,
    deadline=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)
"""Reproducible hypothesis profile: fixed examples, no example database."""


# --- EventSets ---------------------------------------------------------------


def make_eventset(
    index: ArrayLike,
    loss: ArrayLike,
    rates: ArrayLike | None = None,
    *,
    years: Sequence[int] | None = None,
    n_years: int | None = None,
    n_draws: int = 1,
    values: ArrayLike | None = None,
) -> EventSet:
    """A synthetic EventSet with event-major rows.

    Event ``i`` has the rows of its draws ``0 .. n_draws - 1``, in order, all
    with the event's index values.

    Parameters
    ----------
    index : array_like of float
        Index values per event, shape ``(n_events, n_locations)``.
    loss : array_like of float
        Losses per row, shape ``(n_events * n_draws, n_locations)``.
    rates : array_like of float, optional
        Rate per row; by default ``1 / (n_years * n_draws)``.
    years : sequence of int, optional
        Year of each event; by default event ``i`` is in year ``i``.
    n_years : int, optional
        Simulation years; by default the number of events.
    n_draws : int, default 1
        Draws per event.
    values : array_like of float, optional
        Exposure value per location; by default 100 each.
    """
    index = np.asarray(index, dtype=np.float64)
    n_events, n_locations = index.shape
    years = list(range(n_events)) if years is None else list(years)
    total_years = n_events if n_years is None else n_years
    d = n_draws
    if rates is None:
        rates = np.full(n_events * d, 1.0 / (total_years * d))
    events = pd.DataFrame(
        {
            "event_id": np.repeat([f"e{i}" for i in range(n_events)], d),
            "year": np.repeat(years, d),
            "rate": rates,
            "draw_id": np.tile(np.arange(d), n_events),
            "scenario_id": ["prop"] * (n_events * d),
        }
    )
    locations = pd.DataFrame(
        {
            "location_id": [f"L{j}" for j in range(n_locations)],
            "lat": np.full(n_locations, 25.0),
            "lon": np.linspace(-81.0, -80.0, n_locations),
            "value": np.full(n_locations, 100.0) if values is None else values,
            "name": [f"Asset {j}" for j in range(n_locations)],
        }
    )
    metadata = EventSetMetadata(
        hazard=HazardSource(name="synthetic", release="1"),
        index=IndexDefinition(definition="wind at the asset", unit="m/s"),
        loss=LossDefinition(unit="USD", currency="USD"),
        n_years=total_years,
        scenario="property tests",
        provenance=Provenance(
            producer="tests",
            producer_version="0",
            created_at=datetime(2026, 10, 25, tzinfo=UTC),
        ),
        licence="CC0-1.0",
    )
    return EventSet(
        events=events,
        locations=locations,
        index=np.repeat(index, d, axis=0),
        loss=np.asarray(loss, dtype=np.float64),
        metadata=metadata,
    )


@dataclass(frozen=True)
class Layout:
    """Event years, draws and data of a random EventSet, before expansion."""

    n_years: int
    years: list[int]
    n_draws: int
    index: NDArray[np.float64]  # (n_events, n_locations)
    loss: NDArray[np.float64]  # (n_events * n_draws, n_locations), event-major
    values: NDArray[np.float64] | None = None  # (n_locations,); default 100 each


def layout_eventset(layout: Layout, loss_factor: float = 1.0) -> EventSet:
    """The EventSet of a layout, with every loss times ``loss_factor``."""
    return make_eventset(
        layout.index,
        layout.loss * loss_factor,
        years=layout.years,
        n_years=layout.n_years,
        n_draws=layout.n_draws,
        values=layout.values,
    )


def with_scaled_losses(eventset: EventSet, factor: float) -> EventSet:
    """The same one-event-per-year EventSet with every loss times ``factor``."""
    return make_eventset(eventset.index, eventset.loss * factor, eventset.rates)


# --- Data strategies ---------------------------------------------------------


@st.composite
def eventsets(draw: st.DrawFn, max_rows: int = 8, max_locations: int = 3) -> EventSet:
    """Small random EventSets, one event per year: 2-8 rows, 1-3 locations.

    Index values lie on a 0.5 grid in ``[0, 90]``, so they fall below the
    attachment, inside ``[ATTACHMENT, LIMIT)`` and at or above the limit.
    Losses are integers in ``[0, 100]`` (zero rows included), rates are
    positive and unequal.
    """
    n_rows = draw(st.integers(2, max_rows))
    n_locations = draw(st.integers(1, max_locations))
    size = n_rows * n_locations
    index = draw(st.lists(st.integers(0, 180), min_size=size, max_size=size))
    loss = draw(st.lists(st.integers(0, 100), min_size=size, max_size=size))
    weights = draw(st.lists(st.integers(1, 4), min_size=n_rows, max_size=n_rows))
    return make_eventset(
        np.reshape(np.array(index, dtype=np.float64) / 2.0, (n_rows, n_locations)),
        np.reshape(np.array(loss, dtype=np.float64), (n_rows, n_locations)),
        np.array(weights, dtype=np.float64) / n_rows,
    )


@st.composite
def layouts(draw: st.DrawFn) -> Layout:
    """3-8 years, 2..n_years events in random years (repeats and gaps), 1-3
    locations, one or two draws per event. At most one event per year on
    average, so the event basis is defined too."""
    n_years = draw(st.integers(3, 8))
    n_events = draw(st.integers(2, n_years))
    years = draw(
        st.lists(st.integers(0, n_years - 1), min_size=n_events, max_size=n_events)
    )
    n_locations = draw(st.integers(1, 3))
    n_draws = draw(st.sampled_from([1, 2]))
    size = n_events * n_locations
    index = draw(st.lists(st.integers(0, 180), min_size=size, max_size=size))
    loss_size = size * n_draws
    loss = draw(st.lists(st.integers(0, 100), min_size=loss_size, max_size=loss_size))
    return Layout(
        n_years=n_years,
        years=years,
        n_draws=n_draws,
        index=np.reshape(np.array(index, dtype=np.float64) / 2.0, (n_events, -1)),
        loss=np.reshape(np.array(loss, dtype=np.float64), (n_events * n_draws, -1)),
    )


# --- Component strategies ----------------------------------------------------


def step_payouts(max_bins: int = 6) -> st.SearchStrategy[StepPayout]:
    """Uniform step payouts on ``[ATTACHMENT, LIMIT]`` with 1 to ``max_bins``
    bins."""
    return st.integers(1, max_bins).map(lambda n: StepPayout(ATTACHMENT, LIMIT, n))


def scopes() -> st.SearchStrategy[Scope]:
    """The individual and the portfolio scope."""
    return st.sampled_from([Individual(), Portfolio()])


def budgets() -> st.SearchStrategy[Budget | None]:
    """No budget, a zero budget, a binding budget or a slack one."""
    return st.sampled_from([None, Budget(0.0), Budget(0.3), Budget(1.0), Budget(5.0)])


def objectives(
    alphas: Sequence[float] = (0.0, 0.3, 0.7, 1.0),
) -> st.SearchStrategy[Objective]:
    """MSE, E[U] and weighted CVaR with the given alphas and a range of beta."""
    return st.one_of(
        st.just(MSE()),
        st.just(ExpectedUncovered()),
        st.builds(
            WeightedCVaR,
            alpha=st.sampled_from(list(alphas)),
            beta=st.sampled_from([0.5, 0.8, 0.95]),
        ),
    )


# --- Independent numpy measure and objectives --------------------------------


def numpy_measure(
    eventset: EventSet, basis: Basis
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """``(G, p)``: a dense outcome-by-row 0/1 matrix and outcome probabilities.

    Written from SPEC §6.2 without ``basis.py``: ``event_conditional`` one
    outcome per row with ``rate / sum(rate)``; ``event`` every row with its
    rate, then "no event"; ``annual`` every (year, draw) slot of every year
    (no pooling of the empty ones), probability ``1 / (n_years * n_draws)``.
    """
    n_rows = eventset.n_rows
    rates = eventset.rates
    if basis is Basis.EVENT_CONDITIONAL:
        return np.eye(n_rows), rates / rates.sum()
    if basis is Basis.EVENT:
        grouping = np.vstack([np.eye(n_rows), np.zeros((1, n_rows))])
        return grouping, np.append(rates, 1.0 - rates.sum())
    n_years = eventset.metadata.n_years
    n_draws = round(1.0 / (rates[0] * n_years))
    years = eventset.events["year"].to_numpy()
    draws = eventset.events["draw_id"].to_numpy()
    grouping = np.zeros((n_years * n_draws, n_rows))
    for row in range(n_rows):
        grouping[years[row] * n_draws + draws[row], row] = 1.0
    return grouping, np.full(n_years * n_draws, 1.0 / (n_years * n_draws))


def objective_value(
    objective: Objective,
    loss: NDArray[np.float64],
    payout: NDArray[np.float64],
    probability: NDArray[np.float64],
    grouping: NDArray[np.float64] | None = None,
) -> float:
    """SPEC §6 objective over outcomes, in numpy, loss units.

    MSE is the squared summed residual of each outcome (the MAR-24 choice).
    The weighted CVaR uses ``riskmeasures.var_cvar``, the exact discrete
    CVaR, which equals the Rockafellar-Uryasev minimum over ``zeta``.

    Parameters
    ----------
    objective : Objective
        MSE, E[U] or weighted CVaR.
    loss, payout : numpy.ndarray
        Objective-level loss and payout per row.
    probability : numpy.ndarray
        Outcome probabilities.
    grouping : numpy.ndarray, optional
        Outcome-by-row 0/1 matrix (:func:`numpy_measure`); ``None`` means one
        outcome per row (``event_conditional``).
    """

    def per_outcome(values: NDArray[np.float64]) -> NDArray[np.float64]:
        return values if grouping is None else grouping @ values

    if isinstance(objective, MSE):
        return float(probability @ per_outcome(loss - payout) ** 2)
    uncovered = per_outcome(np.maximum(loss - payout, 0.0))
    expected = float(probability @ uncovered)
    if isinstance(objective, ExpectedUncovered):
        return expected
    if isinstance(objective, WeightedCVaR):
        _, cvar = var_cvar(uncovered, probability, objective.beta)
        return objective.alpha * cvar + (1.0 - objective.alpha) * expected
    raise AssertionError(f"no numpy evaluation for {objective!r}")
