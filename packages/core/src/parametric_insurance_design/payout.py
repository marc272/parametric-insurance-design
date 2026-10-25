"""Payout structures (SPEC §4.2, §6 notation).

Owner: MAR-11. The interface is
:class:`~parametric_insurance_design.interfaces.PayoutStructure` (ADR 0002).

:class:`StepPayout` pays ``theta[j, k]`` when entity ``j``'s index falls in
bin ``k``: ``pi_{e,j} = sum_k theta_{j,k} * 1[xi_{e,j} in B_k]``, with
``theta >= 0``, non-decreasing in ``k`` and capped per entity. Index values
outside ``[breakpoints[0], breakpoints[-1])`` are clipped into the first or
last bin, as in the thesis ``_mapping``. Piecewise-linear payouts are parked
(SPEC §9); they would be another subclass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import cvxpy as cp
import numpy as np
from numpy.typing import ArrayLike, NDArray

from parametric_insurance_design.interfaces import PayoutStructure

__all__ = ["PayoutStructure", "StepPayout", "uniform_breakpoints"]


def uniform_breakpoints(
    attachment: float, limit: float, n_bins: int
) -> NDArray[np.float64]:
    """Return ``n_bins + 1`` uniform breakpoints on ``[attachment, limit]``.

    Parameters
    ----------
    attachment : float
        Lowest breakpoint.
    limit : float
        Highest breakpoint, > ``attachment``.
    n_bins : int
        Number of bins, >= 1.

    Returns
    -------
    numpy.ndarray
        Shape ``(n_bins + 1,)`` (thesis ``np.linspace(attachment, limit,
        n_bins + 1)``).
    """
    raise NotImplementedError("MAR-11")  # pragma: no cover


@dataclass(frozen=True)
class StepPayout(PayoutStructure):
    """Monotone, capped step payout on fixed breakpoints.

    Parameters
    ----------
    attachment : float
        Lowest breakpoint (thesis ``ATTACHMENT``).
    limit : float
        Highest breakpoint (thesis ``LIMIT``).
    n_bins : int
        Number of bins.
    breakpoints : tuple of float or None, optional
        Explicit breakpoints, strictly increasing, ``n_bins + 1`` values from
        ``attachment`` to ``limit``. Uniform if None.
    """

    name: ClassVar[str] = "step"

    attachment: float
    limit: float
    n_bins: int
    breakpoints: tuple[float, ...] | None = None

    @property
    def n_params(self) -> int:
        """Number of bins."""
        raise NotImplementedError("MAR-11")  # pragma: no cover

    def parameter_bounds(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Lower and upper bin edges, see ``PayoutStructure``."""
        raise NotImplementedError("MAR-11")  # pragma: no cover

    def basis_matrix(self, index: ArrayLike) -> NDArray[np.float64]:
        """One-hot bin membership, see ``PayoutStructure``."""
        raise NotImplementedError("MAR-11")  # pragma: no cover

    def constraints(
        self, theta: cp.Variable, cap: NDArray[np.float64]
    ) -> tuple[cp.Constraint, ...]:
        """Non-negative, monotone and capped, see ``PayoutStructure``."""
        raise NotImplementedError("MAR-11")  # pragma: no cover

    def evaluate(self, index: ArrayLike, theta: ArrayLike) -> NDArray[np.float64]:
        """Payout per row and entity, see ``PayoutStructure``."""
        raise NotImplementedError("MAR-11")  # pragma: no cover
