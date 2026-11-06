"""Calibrate a parametric cover: choose the payout levels of every unit.

:func:`calibrate` fits a :class:`~petals_parametric.payout.StepPayout` to
the losses of a CLIMADA ``Impact``, given a
:class:`~petals_parametric.index.ParametricIndex` aligned with it. The
**scope** says which units share a design problem:

``"individual"``
    One design problem per unit (exposure point): its own objective on its
    own loss and payout, its own budget ``premium_j <= budget * E[L_j]``
    and its own premium.
``"portfolio"``
    One joint design problem for one risk owner: one payout function per
    unit, but the objective is on the owner's **total** loss and payout,
    ``L_e = sum_j L_{e,j}`` and ``P_e = sum_j P_{e,j}``, under one budget
    on the total premium, ``premium <= budget * E[sum_j L_j]``. Within an
    event, an over-payment at one unit offsets a shortfall at another
    (cross-coverage).

With the same ``budget`` the two scopes spend the same total budget under
the pure premium: the sum of the individual budgets is the portfolio
budget. The individual designs then satisfy the portfolio problem's
constraints, so in sample the portfolio optimum is at most their objective
on the total. Under a cost-of-capital load, the portfolio budget prices the
total payout, whose tail diversifies, while each individual budget prices a
stand-alone payout. Nothing here says that either scope gives the better
cover out of sample.

**Per-unit levels of a portfolio cover are not unique.** The objective of a
joint design problem depends only on the total payout of each event, so
other splits of the same totals across the units are optimal too (any for
the mean squared error, and wherever the linear program has several optimal
solutions for the other objectives). The levels a portfolio cover holds are
the one optimal split the solver returned. Read them, and per-unit metrics
of a portfolio cover, as that.

The objective, the premium and the budget all use the outcome measure of
the ``basis`` (:mod:`~petals_parametric.measure`) over the calibration
years. Rows of the ``Impact`` are events, so with ``basis="annual"`` the
events of a year are summed: the CVaR is a CVaR over years.
"""

from __future__ import annotations

import logging
from collections.abc import Hashable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal, get_args

import numpy as np
import pandas as pd
import scipy.sparse as sp
from numpy.typing import ArrayLike, NDArray

from ._checks import check_real, finite_array, read_only
from .errors import ParametricInputError
from .index import ParametricIndex
from .measure import BASES, OutcomeMeasure, outcome_measure
from .objectives import ExpectedUncovered, MeanSquaredError, Objective, WeightedCVaR
from .payout import StepPayout
from .pricing import CostOfCapitalLoad, Pricing, PurePremium
from .solvers import DesignData, SolverInfo, solve_design

__all__ = [
    "PORTFOLIO",
    "SCOPES",
    "CoverProblem",
    "ParametricCover",
    "Scope",
    "calibrate",
    "loss_matrix",
]

LOGGER = logging.getLogger(__name__)

Scope = Literal["individual", "portfolio"]
"""Which units share a design problem."""

SCOPES: Final[tuple[str, ...]] = get_args(Scope)
"""The values of :data:`Scope`: ``("individual", "portfolio")``."""

PORTFOLIO: Final[str] = "portfolio"
"""``problem_id`` of the portfolio scope's single design problem."""

_COORD_ATOL: Final[float] = 1e-9
_FREQUENCY_RTOL: Final[float] = 1e-9


@dataclass(frozen=True)
class CoverProblem:
    """The solution of one design problem of a cover.

    Attributes
    ----------
    problem_id : str
        The unit id (individual scope) or ``"portfolio"``.
    unit_id : tuple of hashable
        The units of the problem.
    objective_value : float
        The optimal objective value, in loss units (squared for the mean
        squared error), on the calibration years.
    premium : float
        The premium of the problem's payout under the cover's pricing, on
        the calibration years.
    expected_loss : float
        ``E[L]`` of the problem's total loss, on the calibration years.
    budget_bound : float or None
        ``budget * expected_loss``, or None without a budget.
    solver : SolverInfo
        Solver, status and timing.
    diagnostics : mapping of str to float or bool
        ``zero_loss_probability``: ``P(L_o = 0)`` over the outcomes.
        For the weighted CVaR also ``degenerate_tail`` (``beta`` at most
        ``P(L_o = 0)``, so the design minimises ``E[U]``) and
        ``tail_within_one_outcome`` (``1 - beta`` below the smallest
        outcome probability, so the CVaR is the worst outcome alone).
    """

    problem_id: str
    unit_id: tuple[Hashable, ...]
    objective_value: float
    premium: float
    expected_loss: float
    budget_bound: float | None
    solver: SolverInfo
    diagnostics: Mapping[str, float | bool] = field(default_factory=dict)


@dataclass(frozen=True, eq=False)
class ParametricCover:  # pylint: disable=too-many-instance-attributes
    """A calibrated cover: the payout levels of every unit and how they were found.

    Attributes
    ----------
    payout : StepPayout
        The payout structure of every unit.
    objective : Objective
        The objective the levels minimise.
    pricing : Pricing
        The pricing of the premium and the budget.
    scope : {"individual", "portfolio"}
        Which units shared a design problem.
    basis : {"annual", "event"}
        The basis of the objective, the premium and the budget.
    budget : float or None
        ``kappa`` in ``premium <= kappa E[L]``, or None.
    unit_id : tuple of hashable
        The units, in the index's order.
    levels : numpy.ndarray
        ``theta``, the payout levels, shape ``(n_units, n_steps)``, loss
        units. Not unique per unit in the portfolio scope (module
        docstring).
    problems : tuple of CoverProblem
        One per design problem: one per unit, or one for the portfolio.
    calibration_years : numpy.ndarray of int
        The simulation years the cover was calibrated on.
    """

    payout: StepPayout
    objective: Objective
    pricing: Pricing
    scope: str
    basis: str
    budget: float | None
    unit_id: tuple[Hashable, ...]
    levels: NDArray[np.float64]
    problems: tuple[CoverProblem, ...]
    calibration_years: NDArray[np.int64]

    def __post_init__(self) -> None:
        """Validate the shapes and store read-only copies."""
        levels = finite_array(self.levels, "levels", 2)
        if levels.shape != (len(self.unit_id), self.payout.n_steps):
            raise ParametricInputError(
                f"levels must have shape ({len(self.unit_id)}, "
                f"{self.payout.n_steps}), got {levels.shape}"
            )
        if self.scope not in SCOPES:
            raise ParametricInputError(
                f"scope must be one of {list(SCOPES)}, got {self.scope!r}"
            )
        object.__setattr__(self, "levels", read_only(levels))
        object.__setattr__(self, "unit_id", tuple(self.unit_id))
        object.__setattr__(self, "problems", tuple(self.problems))
        object.__setattr__(
            self, "calibration_years", read_only(np.asarray(self.calibration_years))
        )

    @property
    def premium(self) -> float:
        """Sum of the design problems' premiums, on the calibration years.

        In the portfolio scope this is the one problem's premium. In the
        individual scope it is the price of buying each unit's cover
        separately; under a cost-of-capital load the premium of the combined
        payout can be lower, because the load is sub-additive.
        """
        return float(sum(problem.premium for problem in self.problems))

    def payout_matrix(self, index: ParametricIndex) -> NDArray[np.float64]:
        """Return the payout of every event and unit of ``index``.

        Parameters
        ----------
        index : ParametricIndex
            An index with the cover's units, e.g. the test years of the
            calibration index, or another hazard set.

        Returns
        -------
        numpy.ndarray
            Shape ``(index.n_events, n_units)``, loss units.

        Raises
        ------
        ParametricInputError
            If the index's units are not the cover's.
        """
        if tuple(index.unit_id) != self.unit_id:
            raise ParametricInputError(
                "the index's units are not the cover's: "
                f"{list(index.unit_id)[:5]} vs {list(self.unit_id)[:5]}"
            )
        return self.payout.evaluate(index.values, self.levels)

    def payout_impact(self, index: ParametricIndex, impact: Any) -> Any:  # noqa: ANN401
        """Return the payouts as a CLIMADA ``Impact``, aligned with ``impact``.

        Parameters
        ----------
        index : ParametricIndex
            The index the payouts are computed from.
        impact : climada.engine.Impact
            The loss impact of the same events and exposure points, as for
            :func:`calibrate`. Its events, dates, frequencies, coordinates
            and unit are copied.

        Returns
        -------
        climada.engine.Impact
            ``imp_mat`` holds the payout per event and unit, ``at_event``
            its sum over the units, ``eai_exp`` the expected annual payout
            per unit and ``aai_agg`` their sum, so that CLIMADA's tools
            (``calc_freq_curve``, ``impact_per_year``, the plots) work on
            the payouts as on the loss.

        Raises
        ------
        ParametricInputError
            If ``impact`` does not match ``index`` (see :func:`loss_matrix`).
        """
        loss_matrix(index, impact)
        payout = self.payout_matrix(index)
        impact_class = type(impact)
        eai_exp = index.frequency @ payout
        return impact_class(
            event_id=np.asarray(impact.event_id),
            event_name=list(impact.event_name),
            date=np.asarray(impact.date),
            frequency=np.asarray(impact.frequency),
            frequency_unit=impact.frequency_unit,
            coord_exp=np.asarray(impact.coord_exp),
            crs=impact.crs,
            eai_exp=eai_exp,
            at_event=payout.sum(axis=1),
            tot_value=impact.tot_value,
            aai_agg=float(eai_exp.sum()),
            unit=impact.unit,
            imp_mat=sp.csr_matrix(payout),
            haz_type=impact.haz_type,
        )

    def levels_frame(self) -> pd.DataFrame:
        """Return the payout levels as a table.

        Returns
        -------
        pandas.DataFrame
            One row per unit and step: ``unit_id``, ``step``, ``lower`` and
            ``upper`` (the step's index range, ``[lower, upper)``) and
            ``level`` (the payout, loss units).
        """
        edges = self.payout.edges
        n_steps = self.payout.n_steps
        return pd.DataFrame(
            {
                "unit_id": np.repeat(np.array(self.unit_id, dtype=object), n_steps),
                "step": np.tile(np.arange(n_steps), len(self.unit_id)),
                "lower": np.tile(edges[:-1], len(self.unit_id)),
                "upper": np.tile(edges[1:], len(self.unit_id)),
                "level": self.levels.reshape(-1),
            }
        )

    def summary(self) -> pd.DataFrame:
        """Return one row per design problem: objective, premium, budget, solver.

        Returns
        -------
        pandas.DataFrame
            Columns ``problem_id``, ``objective``, ``objective_value``,
            ``premium``, ``expected_loss``, ``budget_bound``, ``solver``,
            ``status`` and the diagnostics.
        """
        rows = []
        for problem in self.problems:
            rows.append(
                {
                    "problem_id": problem.problem_id,
                    "objective": self.objective.name,
                    "objective_value": problem.objective_value,
                    "premium": problem.premium,
                    "expected_loss": problem.expected_loss,
                    "budget_bound": problem.budget_bound,
                    "solver": problem.solver.solver,
                    "status": problem.solver.status,
                    **problem.diagnostics,
                }
            )
        return pd.DataFrame(rows)


def loss_matrix(index: ParametricIndex, impact: Any) -> NDArray[np.float64]:  # noqa: ANN401
    """Return the loss per event and unit of ``impact``, checked against ``index``.

    Parameters
    ----------
    index : ParametricIndex
        The index.
    impact : climada.engine.Impact
        Computed with ``save_mat=True`` for the index's hazard events and
        exposure points, e.g. ``ImpactCalc(exposures, impfset,
        hazard).impact(save_mat=True)``.

    Returns
    -------
    numpy.ndarray
        ``impact.imp_mat`` as a dense ``(n_events, n_units)`` array.

    Raises
    ------
    ParametricInputError
        If the impact has no ``imp_mat``, or its events, frequencies or
        exposure coordinates are not the index's, or a loss is negative or
        not finite.
    """
    matrix = impact.imp_mat
    shape = (index.n_events, index.n_units)
    if matrix is None or tuple(matrix.shape) != shape:
        raise ParametricInputError(
            f"impact.imp_mat must have shape {shape} (events x exposure points); "
            f"got {None if matrix is None else tuple(matrix.shape)}. Compute the "
            "impact with save_mat=True"
        )
    if not np.array_equal(np.asarray(impact.event_id), index.event_id):
        raise ParametricInputError("the impact's event_id are not the index's events")
    if not np.allclose(
        np.asarray(impact.frequency, dtype=float),
        index.frequency,
        rtol=_FREQUENCY_RTOL,
        atol=0.0,
    ):
        raise ParametricInputError("the impact's frequencies are not the index's")
    coords = np.asarray(impact.coord_exp, dtype=float)
    if coords.shape != index.coords.shape or not np.allclose(
        coords, index.coords, rtol=0.0, atol=_COORD_ATOL
    ):
        raise ParametricInputError(
            "the impact's exposure coordinates (coord_exp) are not the index's units"
        )
    loss = finite_array(
        matrix.toarray() if sp.issparse(matrix) else matrix, "imp_mat", 2
    )
    if np.any(loss < 0):
        raise ParametricInputError("the impact holds negative losses")
    return loss


def _check_objective(objective: object) -> Objective:
    """Return ``objective`` if it is one of the module's objectives."""
    if not isinstance(objective, MeanSquaredError | ExpectedUncovered | WeightedCVaR):
        raise ParametricInputError(
            "objective must be MeanSquaredError(), ExpectedUncovered() or "
            f"WeightedCVaR(alpha, beta), got {objective!r}"
        )
    return objective


def _check_pricing(pricing: object) -> Pricing:
    """Return ``pricing`` if it is one of the module's pricings."""
    if not isinstance(pricing, PurePremium | CostOfCapitalLoad):
        raise ParametricInputError(
            "pricing must be PurePremium() or CostOfCapitalLoad(rate, q), "
            f"got {pricing!r}"
        )
    return pricing


def _diagnostics(
    objective: Objective, total_loss: NDArray[np.float64], measure: OutcomeMeasure
) -> dict[str, float | bool]:
    """Record when the tail objective degenerates (``CoverProblem.diagnostics``)."""
    outcome_loss = measure.aggregate(total_loss)
    zero = float(measure.probability[outcome_loss <= 0.0].sum())
    out: dict[str, float | bool] = {"zero_loss_probability": zero}
    if isinstance(objective, WeightedCVaR) and objective.alpha > 0.0:
        smallest = float(measure.probability[measure.probability > 0].min())
        out["degenerate_tail"] = objective.beta <= zero
        out["tail_within_one_outcome"] = 1.0 - objective.beta < smallest
    return out


def _problems(
    scope: str, index: ParametricIndex, loss: NDArray[np.float64]
) -> list[tuple[str, NDArray[np.intp]]]:
    """Return ``(problem_id, unit positions)`` for each design problem."""
    if scope == PORTFOLIO:
        return [(PORTFOLIO, np.arange(loss.shape[1]))]
    return [(str(unit), np.array([j])) for j, unit in enumerate(index.unit_id)]


def calibrate(  # pylint: disable=too-many-arguments,too-many-locals
    index: ParametricIndex,
    impact: Any,  # noqa: ANN401 (climada.engine.Impact)
    *,
    payout: StepPayout,
    objective: Objective,
    basis: str,
    scope: str = "individual",
    pricing: Pricing = PurePremium(),  # noqa: B008 (frozen, so safe to share)
    budget: float | None = None,
    years: ArrayLike | None = None,
) -> ParametricCover:
    """Fit the payout levels of every unit (module docstring).

    Parameters
    ----------
    index : ParametricIndex
        The index, aligned with the impact's events and exposure points.
    impact : climada.engine.Impact
        The loss to cover, with ``imp_mat`` (``save_mat=True``).
    payout : StepPayout
        The payout structure of every unit.
    objective : MeanSquaredError, ExpectedUncovered or WeightedCVaR
        What the levels minimise. The mean squared error needs cvxpy.
    basis : {"annual", "event"}
        The basis of the objective, the premium and the budget. ``"annual"``
        takes the CVaR over simulation years.
    scope : {"individual", "portfolio"}, default "individual"
        One design problem per unit, or one joint problem on the total.
    pricing : PurePremium or CostOfCapitalLoad, default PurePremium()
        The premium the budget constrains and the cover records.
    budget : float, optional
        ``kappa >= 0`` in ``premium <= kappa * E[L]``, per design problem.
        Default: no budget.
    years : array_like of int, optional
        The calibration years, e.g. the training block of
        :func:`~petals_parametric.index.split_years`. Default: all years.

    Returns
    -------
    ParametricCover
        The levels, one :class:`CoverProblem` per design problem, and the
        setup.

    Raises
    ------
    ParametricInputError
        If an argument is invalid, the impact does not match the index, the
        calibration years hold no event, or the frequencies do not fit the
        basis.
    CalibrationError
        If a design problem is not solved to optimality. No problem is
        skipped.
    MissingDependencyError
        If the objective is the mean squared error and cvxpy is missing.

    Examples
    --------
    A tail objective calibrated jointly across the units:

    >>> cover = calibrate(  # doctest: +SKIP
    ...     index,
    ...     impact,
    ...     payout=StepPayout(attachment=1, limit=6, n_steps=5),
    ...     objective=WeightedCVaR(alpha=0.9, beta=0.99),
    ...     basis="annual",
    ...     scope="portfolio",
    ...     budget=1.0,
    ...     years=train,
    ... )
    """
    if not isinstance(index, ParametricIndex):
        raise ParametricInputError(f"index must be a ParametricIndex, got {index!r}")
    if not isinstance(payout, StepPayout):
        raise ParametricInputError(f"payout must be a StepPayout, got {payout!r}")
    objective = _check_objective(objective)
    pricing = _check_pricing(pricing)
    if basis not in BASES:
        raise ParametricInputError(f"basis must be one of {list(BASES)}, got {basis!r}")
    if scope not in SCOPES:
        raise ParametricInputError(
            f"scope must be one of {list(SCOPES)}, got {scope!r}"
        )
    kappa = None if budget is None else check_real("budget", budget, low=0.0)
    loss = loss_matrix(index, impact)
    chosen = index.check_years(years)
    mask = np.isin(index.event_year, chosen)
    if not mask.any():
        raise ParametricInputError("the calibration years hold no event")
    measure = outcome_measure(
        index.event_year[mask],
        index.frequency[mask],
        basis=basis,
        years=chosen,
        n_catalogue_years=index.years.size,
    )
    levels = np.zeros((index.n_units, payout.n_steps))
    problems: list[CoverProblem] = []
    for problem_id, units in _problems(scope, index, loss):
        data = DesignData(
            problem_id=problem_id,
            index=index.values[mask][:, units],
            loss=loss[mask][:, units],
            measure=measure,
        )
        solution = solve_design(data, payout, objective, pricing, kappa)
        levels[units] = solution.levels
        paid = payout.evaluate(data.index, solution.levels).sum(axis=1)
        expected_loss = measure.expectation(data.total_loss)
        diagnostics = _diagnostics(objective, data.total_loss, measure)
        problem = CoverProblem(
            problem_id=problem_id,
            unit_id=tuple(index.unit_id[j] for j in units),
            objective_value=solution.objective_value,
            premium=pricing.premium(paid, measure),
            expected_loss=expected_loss,
            budget_bound=None if kappa is None else kappa * expected_loss,
            solver=solution.info,
            diagnostics=diagnostics,
        )
        problems.append(problem)
        _log(problem, objective)
    return ParametricCover(
        payout=payout,
        objective=objective,
        pricing=pricing,
        scope=scope,
        basis=basis,
        budget=kappa,
        unit_id=tuple(index.unit_id),
        levels=levels,
        problems=tuple(problems),
        calibration_years=chosen,
    )


def _log(problem: CoverProblem, objective: Objective) -> None:
    """Log a solved design problem, and warn when its tail degenerates."""
    LOGGER.info(
        "design problem %r: %s = %.6g, premium %.6g (%s, %.2f s)",
        problem.problem_id,
        objective.name,
        problem.objective_value,
        problem.premium,
        problem.solver.solver,
        problem.solver.seconds,
    )
    if problem.diagnostics.get("degenerate_tail"):
        LOGGER.warning(
            "design problem %r: beta = %s is at most P(L = 0) = %.4g, so the "
            "weighted-CVaR design minimises E[U] only",
            problem.problem_id,
            getattr(objective, "beta", None),
            problem.diagnostics["zero_loss_probability"],
        )
    if problem.diagnostics.get("tail_within_one_outcome"):
        LOGGER.warning(
            "design problem %r: 1 - beta is below the smallest outcome "
            "probability, so the CVaR is the single worst outcome",
            problem.problem_id,
        )
