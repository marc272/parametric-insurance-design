"""Year-block train/test splits (SPEC §6.1, thesis issue M1).

Owner: MAR-22. Splits are by contiguous blocks of simulation years, so every
draw (noise or vulnerability ``draw_id``) of an event lands in the same fold.
Each split returns :class:`~parametric_insurance_design.interfaces.Sample`
objects whose ``years`` include the years without rows. Years follow the
ADR 0002 convention ``1 .. n_years``.
"""

from __future__ import annotations

from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.interfaces import Sample

__all__ = ["holdout", "year_block_kfold"]


def holdout(
    eventset: EventSet, *, train_fraction: float = 0.7
) -> tuple[Sample, Sample]:
    """Train on the first years, test on the rest.

    Parameters
    ----------
    eventset : EventSet
        Full EventSet.
    train_fraction : float, default 0.7
        Share of years in the training block, in ``(0, 1)``.

    Returns
    -------
    train, test : Sample
        Named ``"train"`` and ``"test"``, fold 0.
    """
    raise NotImplementedError("MAR-22")  # pragma: no cover


def year_block_kfold(
    eventset: EventSet, *, k: int = 5
) -> tuple[tuple[Sample, Sample], ...]:
    """k-fold cross-validation over contiguous year blocks.

    Parameters
    ----------
    eventset : EventSet
        Full EventSet.
    k : int, default 5
        Number of folds, >= 2.

    Returns
    -------
    tuple of (Sample, Sample)
        ``(train, test)`` per fold, folds numbered ``0 .. k - 1``.
    """
    raise NotImplementedError("MAR-22")  # pragma: no cover
