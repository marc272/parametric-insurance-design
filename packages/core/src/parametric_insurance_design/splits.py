"""Year-block train/test splits (SPEC §6.1, thesis issue M1).

Splits are by contiguous blocks of simulation years, so every
draw (noise or vulnerability ``draw_id``) of an event lands in the same fold.
Each split returns :class:`~parametric_insurance_design.interfaces.Sample`
objects whose ``years`` include the years without rows. Years follow the
ADR 0002 convention ``0 .. n_years - 1`` (as in IRIS and the thesis), which
the ``EventSet`` constructor enforces, so no calendar-year mapping is needed
here.

No leakage
----------
A year split puts every row of a year in one block. It keeps every draw of an
event together only if the event's rows all carry the same year. The
EventSet contract does not require that (its key is ``(event_id,
draw_id)``), so both splits check it and raise :class:`LeakageError` instead
of splitting an event across folds. :meth:`Sample.select` adds the row-level
guard: a sample refuses rows from years outside its year set.

Block sizes
-----------
* :func:`holdout`: the first ``floor(train_fraction * n_years)`` years train
  (with a ``1e-9`` tolerance, so ``0.7 * 10`` gives 7 years despite floating
  point), the rest test. On the thesis fixture (``n_years = 10_000``) that is
  years ``0 .. 6_999`` and ``7_000 .. 9_999``, SPEC §6.1's "years 1 … 0.7Y"
  in 0-based storage.
* :func:`year_block_kfold`: ``numpy.array_split`` of ``0 .. n_years - 1``
  into ``k`` contiguous blocks (the first ``n_years % k`` blocks get one year
  more). Fold ``i`` tests on block ``i`` and trains on the other blocks.

Every sample must hold at least one row: a split that would leave a block
without rows raises :class:`SplitError` rather than produce a sample that
cannot be calibrated or evaluated.

Overfitting diagnostic
----------------------
:func:`kpi_gap` puts each KPI's in-sample (``train``) and out-of-sample
(``test``) values of one run side by side, with their gap. Joined with the
``runs`` table (scope, ``parameters.n_bins``) it gives the gap as a function
of ``n_bins`` and scope (SPEC §6.1).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from parametric_insurance_design.errors import InputMismatchError
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.interfaces import Sample
from parametric_insurance_design.records import KPIS, Split

__all__ = [
    "GAP_KEY",
    "LeakageError",
    "SplitError",
    "holdout",
    "kpi_gap",
    "year_block_kfold",
]

_TOLERANCE = 1e-9

GAP_KEY: tuple[str, ...] = (
    "run_id",
    "problem_id",
    "fold",
    "basis",
    "level",
    "subject_id",
    "kpi",
    "beta",
)
"""Columns that pair a ``train`` KPI row with its ``test`` row in :func:`kpi_gap`:
the ``kpis`` key without ``eval_split``."""


class SplitError(InputMismatchError):
    """A train/test split cannot be formed from the EventSet or arguments.

    Raised for invalid split parameters (``train_fraction``, ``k``), for a
    block with no years, and for a sample with no rows.
    """


class LeakageError(SplitError):
    """An event's rows carry more than one year.

    A year-block split would then put draws of one event in different folds,
    so the split refuses the EventSet.
    """


def _event_years(eventset: EventSet) -> NDArray[np.int64]:
    """Return the year of each row, after checking each event has one year."""
    events = eventset.events
    years = events["year"].to_numpy(dtype=np.int64)
    per_event = events.groupby("event_id", sort=False)["year"].nunique()
    spread = [str(e) for e in per_event.index[per_event.to_numpy() > 1]]
    if spread:
        examples = ", ".join(repr(e) for e in spread[:5])
        raise LeakageError(
            f"{len(spread)} events have rows in more than one year (e.g. "
            f"{examples}); a year-block split would put draws of one event in "
            "different folds"
        )
    return years


def _sample(
    name: str, row_years: NDArray[np.int64], years: NDArray[np.int64], fold: int
) -> Sample:
    """Return the sample of the rows whose year is in ``years``."""
    rows = np.isin(row_years, years)
    if not rows.any():
        raise SplitError(
            f"the {name} sample of fold {fold} (years {years[0]} .. {years[-1]}) "
            "holds no rows"
        )
    return Sample(name=name, rows=rows, years=years, fold=fold)


def holdout(
    eventset: EventSet, *, train_fraction: float = 0.7
) -> tuple[Sample, Sample]:
    """Train on the first years, test on the rest.

    Parameters
    ----------
    eventset : EventSet
        Full EventSet.
    train_fraction : float, default 0.7
        Share of years in the training block, in ``(0, 1)``. The training
        block is years ``0 .. n_train - 1`` with
        ``n_train = floor(train_fraction * n_years)`` (module docstring).

    Returns
    -------
    train, test : Sample
        Named ``"train"`` and ``"test"``, fold 0. Their ``years`` partition
        ``0 .. n_years - 1`` and their row masks partition the rows.

    Raises
    ------
    SplitError
        If ``train_fraction`` is not a finite number in ``(0, 1)``, either
        block would have no years, or either sample would have no rows.
    LeakageError
        If an event's rows carry more than one year.
    """
    if (
        isinstance(train_fraction, bool)
        or not isinstance(train_fraction, int | float)
        or not math.isfinite(train_fraction)
        or not 0 < train_fraction < 1
    ):
        raise SplitError(
            f"train_fraction must be a number in (0, 1), got {train_fraction!r}"
        )
    row_years = _event_years(eventset)
    n_years = eventset.metadata.n_years
    n_train = math.floor(train_fraction * n_years + _TOLERANCE)
    if not 1 <= n_train <= n_years - 1:
        raise SplitError(
            f"train_fraction {train_fraction} of {n_years} years gives "
            f"{n_train} training years; both blocks need at least one year"
        )
    all_years = np.arange(n_years, dtype=np.int64)
    train = _sample(Split.TRAIN.value, row_years, all_years[:n_train], 0)
    test = _sample(Split.TEST.value, row_years, all_years[n_train:], 0)
    return train, test


def year_block_kfold(
    eventset: EventSet, *, k: int = 5
) -> tuple[tuple[Sample, Sample], ...]:
    """k-fold cross-validation over contiguous year blocks.

    Parameters
    ----------
    eventset : EventSet
        Full EventSet.
    k : int, default 5
        Number of folds, ``2 <= k <= n_years``.

    Returns
    -------
    tuple of (Sample, Sample)
        ``(train, test)`` per fold, folds numbered ``0 .. k - 1``. Fold ``i``
        tests on the ``i``-th block of contiguous years and trains on the
        others. The test samples partition the rows, and their ``years``
        partition ``0 .. n_years - 1``.

    Raises
    ------
    SplitError
        If ``k`` is not an int in ``[2, n_years]``, or a sample of some fold
        would have no rows.
    LeakageError
        If an event's rows carry more than one year.
    """
    n_years = eventset.metadata.n_years
    if isinstance(k, bool) or not isinstance(k, int) or not 2 <= k <= n_years:
        raise SplitError(f"k must be an int in [2, {n_years}] (n_years), got {k!r}")
    row_years = _event_years(eventset)
    all_years = np.arange(n_years, dtype=np.int64)
    folds: list[tuple[Sample, Sample]] = []
    for fold, block in enumerate(np.array_split(all_years, k)):
        others = np.setdiff1d(all_years, block)
        train = _sample(Split.TRAIN.value, row_years, others, fold)
        test = _sample(Split.TEST.value, row_years, block, fold)
        folds.append((train, test))
    return tuple(folds)


def kpi_gap(kpis: pd.DataFrame) -> pd.DataFrame:
    """Pair in-sample and out-of-sample KPI values (overfitting diagnostic).

    Parameters
    ----------
    kpis : pandas.DataFrame
        A ``kpis`` table (``records.KPIS``), e.g. ``ResultStore.read("kpis")``
        or ``evaluate.kpis`` output, with ``train`` and ``test`` rows. Rows of
        other splits (``full``) are ignored.

    Returns
    -------
    pandas.DataFrame
        One row per :data:`GAP_KEY` with columns :data:`GAP_KEY`, ``train``
        (in-sample value), ``test`` (out-of-sample value) and
        ``gap = test - train``, sorted by the key. A positive gap means the
        KPI is larger out of sample (worse, for a risk measure).

    Raises
    ------
    RecordSchemaError
        If ``kpis`` is not a valid ``kpis`` table.
    InputMismatchError
        If a ``train`` row has no ``test`` row or the reverse. A partial
        pairing would silently drop KPIs.
    """
    KPIS.validate(kpis)
    key = list(GAP_KEY)
    train = kpis.loc[kpis["eval_split"] == Split.TRAIN.value, [*key, "value"]]
    test = kpis.loc[kpis["eval_split"] == Split.TEST.value, [*key, "value"]]
    merged = train.merge(
        test,
        on=key,
        how="outer",
        suffixes=("_train", "_test"),
        indicator=True,
        validate="one_to_one",
    )
    unpaired = merged[merged["_merge"] != "both"]
    if len(unpaired):
        row = unpaired.iloc[0]
        side = "train" if row["_merge"] == "left_only" else "test"
        raise InputMismatchError(
            f"{len(unpaired)} KPI rows have no counterpart in the other split; "
            f"e.g. a {side} row of run {row['run_id']!r}, problem "
            f"{row['problem_id']!r}, kpi {row['kpi']!r}, fold {row['fold']}"
        )
    out = merged.drop(columns="_merge").rename(
        columns={"value_train": "train", "value_test": "test"}
    )
    out["gap"] = out["test"] - out["train"]
    # Explicit column order: pandas < 2.2 orders an empty outer merge differently.
    out = out[[*key, "train", "test", "gap"]]
    return out.sort_values(key, kind="stable").reset_index(drop=True)
