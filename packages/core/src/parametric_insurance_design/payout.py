"""Payout structures (SPEC §4.2, §6 notation).

Owner: MAR-11 → MAR-170 (``below_attachment``). The interface is
:class:`~parametric_insurance_design.interfaces.PayoutStructure` (ADR 0002).

:class:`StepPayout` pays ``theta[j, k]`` when entity ``j``'s index falls in
bin ``k``: ``pi_{e,j} = sum_k theta_{j,k} * 1[xi_{e,j} in B_k]``, with
``theta >= 0``, non-decreasing in ``k`` and capped per entity. Index values
at or above ``breakpoints[-1]`` are clipped into the last bin, as in the
thesis ``_mapping``. Values below ``breakpoints[0]`` are clipped into the
first bin (``below_attachment="first_bin"``, the default and the thesis code)
or pay nothing (``below_attachment="zero"``). Piecewise-linear payouts are
parked (SPEC §9); they would be another subclass.

Bin semantics (thesis ``OptimizationConstructor._mapping`` and
``get_payout_for_asset``, reproduced exactly under ``"first_bin"``):

* Bins are half-open, ``B_k = [b_k, b_{k+1})`` for ``k = 0 .. n_bins - 1``.
  A value equal to an interior breakpoint ``b_k`` belongs to bin ``k``, and a
  value equal to the attachment ``b_0`` to bin 0, in both modes.
* Values below the attachment ``b_0``:

  - ``"first_bin"`` (default; thesis code and thesis §3.3.1): they fall into
    bin 0. In particular a zero index (no hazard) pays ``theta[j, 0]``; the
    optimiser is free to set it to 0, and sets it positive whenever bin 0
    carries loss.
  - ``"zero"`` (thesis §3.3 (3): an attachment point "below which no payout
    is triggered"): they are in no bin (:data:`NO_BIN`), pay 0, and have an
    all-zero row in :meth:`StepPayout.basis_matrix`.

  On the ``event`` and ``annual`` bases (``basis.py``), rows that a threshold
  filter dropped and years without rows are outcomes that pay nothing. Under
  ``"zero"`` a kept row whose index is below the attachment at every entity
  pays nothing too, so dropping such rows with zero loss changes neither the
  design nor its premium: the filter is then for speed only, as SPEC §5 says.
  Under ``"first_bin"`` such a kept row pays ``theta[j, 0]`` and a dropped
  one pays nothing, so the design depends on which rows the EventSet holds
  (design review MAR-161, finding F1; ``tests/test_filter_invariance.py``).
* Values at or above the limit ``b_n`` fall into the last bin. The thesis
  clips to ``b_n - 1e-12`` before the lookup; this module does the same and
  then clamps the bin number into ``[0, n_bins - 1]``, as
  ``get_payout_for_asset`` does. The clamp only matters where ``b_n - 1e-12``
  rounds back to ``b_n`` (limits of about 1e4 and above); there the thesis
  ``_mapping`` raises ``IndexError`` and this module uses the last bin.
* Non-finite index values raise :class:`InputMismatchError`. The thesis put
  NaN into the last bin (``get_payout_for_asset``) or crashed (``_mapping``).
* The last bin must be at least ``1e-12`` wide. Narrower, the thesis clip
  point would lie below it and values at or above the limit would land in
  bin ``n_bins - 2``; such breakpoints raise :class:`ComponentConfigError`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from numbers import Real
from typing import ClassVar, Final, Literal, get_args

import cvxpy as cp
import numpy as np
from numpy.typing import ArrayLike, NDArray

from parametric_insurance_design.errors import (
    ComponentConfigError,
    InputMismatchError,
)
from parametric_insurance_design.interfaces import PayoutStructure

__all__ = [
    "BELOW_ATTACHMENT_MODES",
    "NO_BIN",
    "THESIS_UPPER_EPS",
    "BelowAttachment",
    "PayoutStructure",
    "StepPayout",
    "uniform_breakpoints",
]

THESIS_UPPER_EPS: float = 1e-12
"""Offset below the limit that index values are clipped to (thesis ``eps``)."""

BelowAttachment = Literal["first_bin", "zero"]
"""What a :class:`StepPayout` pays for an index below the attachment.

``"first_bin"``: the first bin's level ``theta[j, 0]`` (thesis code; the
default). ``"zero"``: nothing (thesis text, §3.3 (3)). See the module
docstring."""

BELOW_ATTACHMENT_MODES: Final[tuple[str, ...]] = get_args(BelowAttachment)
"""The values of :data:`BelowAttachment`, in order: ``("first_bin", "zero")``."""

NO_BIN: Final[int] = -1
"""Bin number :meth:`StepPayout.bin_index` gives an index value in no bin: a
value below the attachment under ``below_attachment="zero"``."""


def _check_range(attachment: object, limit: object, n_bins: object) -> None:
    """Validate attachment, limit and bin count.

    Raises
    ------
    ComponentConfigError
        If ``n_bins`` is not an int >= 1, or ``attachment`` and ``limit`` are
        not finite reals with ``attachment < limit``.
    """
    if isinstance(n_bins, bool) or not isinstance(n_bins, int | np.integer):
        raise ComponentConfigError(f"n_bins must be an int, got {n_bins!r}")
    if n_bins < 1:
        raise ComponentConfigError(f"n_bins must be >= 1, got {n_bins}")
    bounds: list[float] = []
    for name, value in (("attachment", attachment), ("limit", limit)):
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ComponentConfigError(f"{name} must be a real number, got {value!r}")
        if not math.isfinite(float(value)):
            raise ComponentConfigError(f"{name} must be finite, got {value!r}")
        bounds.append(float(value))
    if not bounds[0] < bounds[1]:
        raise ComponentConfigError(
            f"attachment must be < limit, got attachment={attachment}, limit={limit}"
        )


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

    Raises
    ------
    ComponentConfigError
        If ``n_bins < 1``, or ``attachment`` and ``limit`` are not finite with
        ``attachment < limit``.
    """
    _check_range(attachment, limit, n_bins)
    return np.linspace(float(attachment), float(limit), int(n_bins) + 1)


def _finite_array(values: ArrayLike, name: str, ndim: int) -> NDArray[np.float64]:
    """Convert to a float array of the given dimension and check it is finite.

    Raises
    ------
    InputMismatchError
        If the values are not numeric, have another dimension, or are not
        finite.
    """
    try:
        arr = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise InputMismatchError(f"{name} must be numeric: {exc}") from exc
    if arr.ndim != ndim:
        raise InputMismatchError(f"{name} must be {ndim}-D, got shape {arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise InputMismatchError(f"{name} must be finite")
    return arr


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
    below_attachment : {"first_bin", "zero"}, default "first_bin"
        What an index value below ``attachment`` pays (:data:`BelowAttachment`).
        ``"first_bin"``: the first bin's level, as the thesis code does.
        ``"zero"``: nothing; the value is in no bin. A value equal to
        ``attachment`` is in bin 0 either way.

    Raises
    ------
    ComponentConfigError
        If the parameters are invalid: ``n_bins < 1``, ``attachment >=
        limit``, non-finite values, or explicit breakpoints of the wrong
        length, not strictly increasing, or not starting at ``attachment``
        and ending at ``limit`` exactly; a last bin narrower than
        :data:`THESIS_UPPER_EPS`; or a ``below_attachment`` that is not one of
        :data:`BELOW_ATTACHMENT_MODES`.

    Notes
    -----
    See the module docstring for the bin semantics (half-open bins, values
    below the attachment, clipping at or above the limit), and why
    ``"zero"`` makes a threshold filter at the attachment exact on the
    ``event`` and ``annual`` bases.

    Examples
    --------
    >>> payout = StepPayout(attachment=20.0, limit=70.0, n_bins=5)
    >>> payout.edges.tolist()
    [20.0, 30.0, 40.0, 50.0, 60.0, 70.0]
    >>> payout.bin_index([0.0, 20.0, 29.9, 30.0, 69.9, 70.0, 99.0]).tolist()
    [0, 0, 0, 1, 4, 4, 4]
    >>> zero = StepPayout(20.0, 70.0, 5, below_attachment="zero")
    >>> zero.bin_index([0.0, 19.9, 20.0, 29.9, 30.0, 70.0]).tolist()
    [-1, -1, 0, 0, 1, 4]
    """

    name: ClassVar[str] = "step"

    attachment: float
    limit: float
    n_bins: int
    breakpoints: tuple[float, ...] | None = None
    below_attachment: BelowAttachment = "first_bin"
    _edges: NDArray[np.float64] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Validate the parameters and store the breakpoints read-only."""
        _check_range(self.attachment, self.limit, self.n_bins)
        if (
            not isinstance(self.below_attachment, str)
            or self.below_attachment not in BELOW_ATTACHMENT_MODES
        ):
            raise ComponentConfigError(
                f"below_attachment must be one of {list(BELOW_ATTACHMENT_MODES)}, "
                f"got {self.below_attachment!r}"
            )
        if self.breakpoints is None:
            edges = uniform_breakpoints(self.attachment, self.limit, self.n_bins)
        else:
            edges = self._check_breakpoints(self.breakpoints)
            object.__setattr__(self, "breakpoints", tuple(edges.tolist()))
        if edges[-1] - THESIS_UPPER_EPS < edges[-2]:
            # The thesis clip point would fall below the last bin and send
            # values at or above the limit to bin n - 2.
            raise ComponentConfigError(
                f"the last bin [{edges[-2]}, {edges[-1]}) must be at least "
                f"{THESIS_UPPER_EPS} wide (thesis clipping offset)"
            )
        edges.setflags(write=False)
        object.__setattr__(self, "_edges", edges)

    def _check_breakpoints(self, breakpoints: object) -> NDArray[np.float64]:
        """Validate explicit breakpoints and return them as an array."""
        try:
            edges = np.array(breakpoints, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise ComponentConfigError(f"breakpoints must be numeric: {exc}") from exc
        if edges.shape != (self.n_bins + 1,):
            raise ComponentConfigError(
                f"breakpoints must hold n_bins + 1 = {self.n_bins + 1} values, "
                f"got shape {edges.shape}"
            )
        if not np.all(np.isfinite(edges)):
            raise ComponentConfigError("breakpoints must be finite")
        if not np.all(np.diff(edges) > 0):
            raise ComponentConfigError("breakpoints must be strictly increasing")
        if edges[0] != float(self.attachment) or edges[-1] != float(self.limit):
            raise ComponentConfigError(
                f"breakpoints must run from attachment={self.attachment} to "
                f"limit={self.limit}, got {edges[0]} to {edges[-1]}"
            )
        return edges

    @property
    def n_params(self) -> int:
        """Number of bins."""
        return int(self.n_bins)

    @property
    def edges(self) -> NDArray[np.float64]:
        """Breakpoints ``b_0 < ... < b_n``, shape ``(n_bins + 1,)``, read-only."""
        return self._edges

    def parameter_bounds(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Lower and upper bin edges, see ``PayoutStructure``.

        Returns
        -------
        lower, upper : numpy.ndarray
            ``edges[:-1]`` and ``edges[1:]``, shape ``(n_bins,)`` each. Bin
            ``k`` is ``[lower[k], upper[k])``; the last bin also takes the
            clipped values at or above the limit, and under
            ``below_attachment="first_bin"`` the first bin the values below
            the attachment (under ``"zero"`` they are in no bin). The same in
            both modes.
        """
        return self._edges[:-1].copy(), self._edges[1:].copy()

    def bin_index(self, index: ArrayLike) -> NDArray[np.intp]:
        """Bin number of each index value, with the thesis clipping.

        Parameters
        ----------
        index : array_like of float
            Index values, any shape. Finite.

        Returns
        -------
        numpy.ndarray of int
            Same shape as ``index``, values in ``[0, n_bins - 1]``; under
            ``below_attachment="zero"``, :data:`NO_BIN` (-1) for the values
            below the attachment.

        Raises
        ------
        InputMismatchError
            If ``index`` is not numeric or not finite.
        """
        x = _finite_array(index, "index", np.ndim(index))
        edges = self._edges
        clipped = np.clip(x, edges[0], edges[-1] - THESIS_UPPER_EPS)
        k = np.searchsorted(edges, clipped, side="right") - 1
        k = np.clip(k, 0, self.n_params - 1).astype(np.intp)
        if self.below_attachment == "zero":
            k = np.where(x < edges[0], NO_BIN, k).astype(np.intp)
        return k

    def basis_matrix(self, index: ArrayLike) -> NDArray[np.float64]:
        """One-hot bin membership, see ``PayoutStructure``.

        Parameters
        ----------
        index : array_like of float
            Index values of one entity, shape ``(n_rows,)``. Finite.

        Returns
        -------
        numpy.ndarray
            ``M`` with shape ``(n_rows, n_bins)``: ``M[e, k] = 1`` if row
            ``e`` falls in bin ``k`` (after clipping), else 0. Every row has
            at most one 1: exactly one under ``below_attachment="first_bin"``
            (thesis ``_mapping``); under ``"zero"`` a row whose index is
            below the attachment is all zeros, so it pays nothing for every
            ``theta`` (ADR 0002 amendment MAR-170).

        Raises
        ------
        InputMismatchError
            If ``index`` is not 1-D or not finite.
        """
        x = _finite_array(index, "index", 1)
        k = self.bin_index(x)
        m = np.zeros((x.shape[0], self.n_params), dtype=np.float64)
        rows = np.flatnonzero(k != NO_BIN)
        m[rows, k[rows]] = 1.0
        return m

    def constraints(
        self, theta: cp.Variable, cap: NDArray[np.float64]
    ) -> tuple[cp.Constraint, ...]:
        """Non-negative, monotone and capped, see ``PayoutStructure``.

        Parameters
        ----------
        theta : cvxpy.Variable
            Shape ``(n_entities, n_bins)``. Any cvxpy expression of that shape
            works, e.g. a slice of a shared variable.
        cap : numpy.ndarray
            Maximum payout per entity, shape ``(n_entities,)``, finite and
            >= 0.

        Returns
        -------
        tuple of cvxpy.Constraint
            ``theta >= 0``; ``theta[:, k] <= theta[:, k + 1]`` (omitted when
            ``n_bins == 1``); ``theta[j, :] <= cap[j]``. Thesis: ``P >= 0``
            (non-negative variable), ``cp.diff(P[j]) >= 0`` and
            ``P[j] <= max_loss_j``.

        Raises
        ------
        InputMismatchError
            If ``theta`` or ``cap`` has the wrong shape, or ``cap`` is not
            finite and >= 0.
        """
        shape = tuple(theta.shape)
        if len(shape) != 2 or shape[1] != self.n_params:
            raise InputMismatchError(
                f"theta must have shape (n_entities, {self.n_params}), got {shape}"
            )
        caps = _finite_array(cap, "cap", 1)
        if caps.shape != (shape[0],):
            raise InputMismatchError(
                f"cap must have shape ({shape[0]},), got {caps.shape}"
            )
        if np.any(caps < 0):
            raise InputMismatchError("cap must be >= 0")
        out: list[cp.Constraint] = [theta >= 0]
        if self.n_params > 1:
            out.append(theta[:, 1:] >= theta[:, :-1])
        out.append(theta <= np.repeat(caps[:, None], self.n_params, axis=1))
        return tuple(out)

    def evaluate(self, index: ArrayLike, theta: ArrayLike) -> NDArray[np.float64]:
        """Payout per row and entity, see ``PayoutStructure``.

        Thesis ``get_payout_for_asset(index[:, j], theta[j], edges)`` for
        each entity ``j`` under ``below_attachment="first_bin"``.

        Parameters
        ----------
        index : array_like of float
            Shape ``(n_rows, n_entities)``. Finite.
        theta : array_like of float
            Shape ``(n_entities, n_bins)``. Finite. Not checked against the
            constraints, so any parameters can be evaluated.

        Returns
        -------
        numpy.ndarray
            ``out[e, j] = theta[j, bin_index(index[e, j])]``, and 0 where the
            index is in no bin (below the attachment under
            ``below_attachment="zero"``), shape ``(n_rows, n_entities)``.
            Equal to ``basis_matrix(index[:, j]) @ theta[j]``.

        Raises
        ------
        InputMismatchError
            If the shapes do not fit or a value is not finite.
        """
        xi = _finite_array(index, "index", 2)
        th = _finite_array(theta, "theta", 2)
        want = (xi.shape[1], self.n_params)
        if th.shape != want:
            raise InputMismatchError(f"theta must have shape {want}, got {th.shape}")
        k = self.bin_index(xi)
        entity = np.arange(xi.shape[1])[None, :]
        if self.below_attachment == "first_bin":
            return th[entity, k]
        unpaid = k == NO_BIN
        return np.where(unpaid, 0.0, th[entity, np.where(unpaid, 0, k)])
