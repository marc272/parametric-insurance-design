"""Tests for the thesis noise layer (MAR-10).

Bit-identical parity with the thesis function is tested in
``parity/tests/test_noise_parity.py``. The last test here repeats the check
against the committed thesis digests on the parity fixture, so that CI runs it
while ``parity/tests`` is not yet in CI (MAR-86).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import platform
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from parametric_insurance_design.errors import ComponentConfigError, InputMismatchError
from parametric_insurance_design.eventset import EventSet, ThresholdFilterRecord
from parametric_insurance_design.noise import NoiseKind, add_noise

REPO_ROOT = Path(__file__).resolve().parents[3]
PARITY_EVENTSET = REPO_ROOT / "parity" / "tests" / "data" / "thesis_eventset"
PARITY_DIGESTS = REPO_ROOT / "parity" / "golden" / "noise_digests.json"


def _noise(
    eventset: EventSet,
    seed: int = 42,
    *,
    level: float = 0.3,
    kind: NoiseKind = "heteroscedastic",
    n_copies: int = 4,
    bounds: tuple[float, float] = (20.0, 70.0),
    location_ids: Sequence[str] | None = None,
) -> EventSet:
    return add_noise(
        eventset,
        level=level,
        kind=kind,
        n_copies=n_copies,
        rng=np.random.default_rng(seed),
        bounds=bounds,
        location_ids=location_ids,
    )


def _reference(
    eventset: EventSet,
    *,
    level: float,
    kind: NoiseKind,
    n_copies: int,
    seed: int,
    bounds: tuple[float, float] = (20.0, 70.0),
    order: list[int] | None = None,
) -> np.ndarray:
    """Straightforward re-statement of the thesis algorithm."""
    rng = np.random.default_rng(seed)
    index = np.repeat(eventset.index, n_copies, axis=0)
    loss = np.repeat(eventset.loss, n_copies, axis=0)
    for j in range(eventset.n_locations) if order is None else order:
        if kind == "homoscedastic":
            sigma = np.full(len(loss), np.sqrt(np.log(1.0 + level**2)))
        else:
            r = np.clip((index[:, j] - bounds[0]) / (bounds[1] - bounds[0]), 0.0, 1.0)
            sigma = np.sqrt(np.log(1.0 + (level * r) ** 2))
        loss[:, j] = loss[:, j] * np.exp(
            rng.normal(loc=-0.5 * sigma**2, scale=sigma, size=len(loss))
        )
    return loss


# -- expansion, rates, metadata ----------------------------------------------


def test_expansion_shapes_and_draw_ids(toy_eventset: EventSet) -> None:
    noisy = _noise(toy_eventset, n_copies=3)
    assert noisy.n_rows == 9
    assert noisy.loss.shape == noisy.index.shape == (9, 2)
    events = noisy.events
    assert events["event_id"].tolist() == ["ev1"] * 3 + ["ev2"] * 3 + ["ev3"] * 3
    assert events["draw_id"].tolist() == [0, 1, 2] * 3
    assert events["year"].tolist() == [0] * 3 + [1] * 3 + [2] * 3
    assert events["scenario_id"].tolist() == ["toy"] * 9
    # The index is copied, not perturbed.
    np.testing.assert_array_equal(noisy.index, np.repeat(toy_eventset.index, 3, axis=0))
    assert noisy.locations.equals(toy_eventset.locations)
    # The input is not modified.
    assert toy_eventset.n_rows == 3


def test_rate_convention_keeps_event_totals(toy_eventset: EventSet) -> None:
    events = toy_eventset.events.assign(rate=[0.1, 0.2, 0.4])
    source = dataclasses.replace(toy_eventset, events=events)
    noisy = _noise(source, n_copies=4)
    np.testing.assert_array_equal(noisy.rates, np.repeat([0.1, 0.2, 0.4], 4) / 4)
    totals = noisy.rates.reshape(3, 4).sum(axis=1)  # rows are event-major
    np.testing.assert_allclose(totals, [0.1, 0.2, 0.4], rtol=1e-15)


def test_single_copy_keeps_rows_and_rates(toy_eventset: EventSet) -> None:
    noisy = _noise(toy_eventset, n_copies=1)
    np.testing.assert_array_equal(noisy.rates, toy_eventset.rates)
    assert noisy.events["draw_id"].tolist() == [0, 0, 0]


def test_metadata_records_noise_and_keeps_filters(toy_eventset: EventSet) -> None:
    filtered = toy_eventset.filter_threshold(20.0)
    noisy = _noise(filtered, n_copies=2, bounds=(25.0, 60.0))
    meta = noisy.metadata
    assert meta.filters == filtered.metadata.filters
    assert isinstance(meta.filters[0], ThresholdFilterRecord)
    assert meta.scenario.startswith("toy | noise: thesis noise layer")
    assert "kind=heteroscedastic, level=0.3, n_copies=2" in meta.scenario
    assert "bounds=(25.0, 60.0), locations=all" in meta.scenario
    assert meta.n_years == filtered.metadata.n_years
    assert meta.provenance == filtered.metadata.provenance
    homo = _noise(toy_eventset, kind="homoscedastic", location_ids=["B"])
    assert "bounds" not in homo.metadata.scenario
    assert homo.metadata.scenario.endswith("locations=B; rates divided by n_copies")


def test_output_round_trips_through_parquet(
    toy_eventset: EventSet, tmp_path: Path
) -> None:
    noisy = _noise(toy_eventset)
    assert EventSet.from_parquet(noisy.to_parquet(tmp_path / "es")).equals(noisy)


# -- determinism and the random stream ---------------------------------------


def test_same_seed_same_draws(toy_eventset: EventSet) -> None:
    first = _noise(toy_eventset, 7)
    assert first.equals(_noise(toy_eventset, 7))
    assert not np.array_equal(first.loss, _noise(toy_eventset, 8).loss)


def test_generator_is_consumed(toy_eventset: EventSet) -> None:
    rng = np.random.default_rng(3)
    kwargs: dict[str, Any] = {"level": 0.3, "kind": "homoscedastic", "n_copies": 2}
    first = add_noise(toy_eventset, rng=rng, **kwargs)
    second = add_noise(toy_eventset, rng=rng, **kwargs)
    assert not np.array_equal(first.loss, second.loss)
    # One normal draw per output row and perturbed location, per call.
    replay = np.random.default_rng(3)
    replay.normal(size=2 * 6 * 2)
    assert replay.normal() == rng.normal()


@pytest.mark.parametrize("kind", ["homoscedastic", "heteroscedastic"])
def test_matches_reference_algorithm(toy_eventset: EventSet, kind: NoiseKind) -> None:
    noisy = _noise(toy_eventset, 11, kind=kind, level=0.5, n_copies=5)
    expected = _reference(toy_eventset, level=0.5, kind=kind, n_copies=5, seed=11)
    assert np.array_equal(noisy.loss, expected)


def test_location_order_is_the_call_order(toy_eventset: EventSet) -> None:
    kwargs: dict[str, Any] = {"kind": "homoscedastic", "n_copies": 3}
    forward = _noise(toy_eventset, **kwargs)
    backward = _noise(toy_eventset, location_ids=["B", "A"], **kwargs)
    assert not np.array_equal(forward.loss, backward.loss)
    expected = _reference(
        toy_eventset, level=0.3, kind="homoscedastic", n_copies=3, seed=42, order=[1, 0]
    )
    assert np.array_equal(backward.loss, expected)


def test_subset_leaves_other_locations_unchanged(toy_eventset: EventSet) -> None:
    noisy = _noise(toy_eventset, kind="homoscedastic", location_ids=["B"])
    np.testing.assert_array_equal(
        noisy.loss[:, 0], np.repeat(toy_eventset.loss[:, 0], 4)
    )
    assert not np.array_equal(noisy.loss[:, 1], np.repeat(toy_eventset.loss[:, 1], 4))


# -- noise models -------------------------------------------------------------


def test_zero_level_changes_nothing(toy_eventset: EventSet) -> None:
    for kind in ("homoscedastic", "heteroscedastic"):
        noisy = _noise(toy_eventset, level=0.0, kind=kind)  # type: ignore[arg-type]
        np.testing.assert_array_equal(
            noisy.loss, np.repeat(toy_eventset.loss, 4, axis=0)
        )


def test_heteroscedastic_bounds_come_from_the_caller(toy_eventset: EventSet) -> None:
    repeated = np.repeat(toy_eventset.loss, 4, axis=0)
    # Index 10/15 (ev1) is below the default low bound 20: factor exactly 1.
    default = _noise(toy_eventset, level=0.8)
    np.testing.assert_array_equal(default.loss[:4], repeated[:4])
    assert not np.array_equal(default.loss[4:], repeated[4:])
    # Every index is below 60: no noise at all.
    quiet = _noise(toy_eventset, level=0.8, bounds=(60.0, 90.0))
    np.testing.assert_array_equal(quiet.loss, repeated)
    # Moving the bounds changes the draws' scale, not the stream.
    shifted = _noise(toy_eventset, level=0.8, bounds=(0.0, 50.0))
    expected = _reference(
        toy_eventset, level=0.8, kind="heteroscedastic", n_copies=4, seed=42,
        bounds=(0.0, 50.0),
    )  # fmt: skip
    assert np.array_equal(shifted.loss, expected)
    assert not np.array_equal(shifted.loss, default.loss)


def test_factor_has_mean_one_and_level_as_cv(toy_eventset: EventSet) -> None:
    noisy = _noise(toy_eventset, kind="homoscedastic", level=0.3, n_copies=20_000)
    factor = noisy.loss[noisy.events["event_id"] == "ev3", 0] / 10.0
    assert factor.mean() == pytest.approx(1.0, abs=0.01)
    assert factor.std() / factor.mean() == pytest.approx(0.3, abs=0.01)
    assert (noisy.loss >= 0).all()


# -- typed errors -------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        pytest.param({"kind": "gaussian"}, "kind must be one of", id="kind"),
        pytest.param({"n_copies": 0}, "n_copies must be >= 1", id="copies-zero"),
        pytest.param({"n_copies": 2.0}, "n_copies must be an int", id="copies-float"),
        pytest.param({"n_copies": True}, "n_copies must be an int", id="copies-bool"),
        pytest.param({"level": -0.1}, "level must be >= 0", id="level-negative"),
        pytest.param({"level": float("nan")}, "level must be finite", id="level-nan"),
        pytest.param({"level": "0.3"}, "level must be a real number", id="level-str"),
        pytest.param({"bounds": (70.0, 20.0)}, "low < high", id="bounds-order"),
        pytest.param({"bounds": (20.0, 20.0)}, "low < high", id="bounds-equal"),
        pytest.param({"bounds": (20.0,)}, "must be a pair", id="bounds-length"),
        pytest.param({"bounds": None}, "must be a pair", id="bounds-none"),
        pytest.param(
            {"bounds": (0.0, np.inf)}, "bounds\\[1\\] must be finite", id="inf"
        ),
        pytest.param({"rng": 42}, "numpy.random.Generator", id="seed-not-generator"),
        pytest.param(
            {"rng": np.random.RandomState(42)}, "numpy.random.Generator", id="legacy"
        ),
    ],
)
def test_invalid_parameters_raise(
    toy_eventset: EventSet, kwargs: dict[str, Any], message: str
) -> None:
    arguments: dict[str, Any] = {
        "level": 0.3,
        "kind": "heteroscedastic",
        "n_copies": 2,
        "rng": np.random.default_rng(0),
        **kwargs,
    }
    with pytest.raises(ComponentConfigError, match=message):
        add_noise(toy_eventset, **arguments)


@pytest.mark.parametrize(
    ("location_ids", "message"),
    [
        pytest.param(["A", "C"], "unknown location_ids: \\['C'\\]", id="unknown"),
        pytest.param(["A", "A"], "repeated location_ids: \\['A'\\]", id="repeated"),
        pytest.param([], "location_ids is empty", id="empty"),
        pytest.param("AB", "not the string", id="string"),
    ],
)
def test_bad_location_ids_raise(
    toy_eventset: EventSet, location_ids: list[str] | str, message: str
) -> None:
    with pytest.raises(InputMismatchError, match=message):
        _noise(toy_eventset, location_ids=location_ids)


def test_input_with_draws_is_refused(toy_eventset: EventSet) -> None:
    noisy = _noise(toy_eventset, n_copies=2)
    with pytest.raises(InputMismatchError, match="without draws"):
        _noise(noisy)


# -- thesis digest on the parity fixture (MAR-10 acceptance, CI copy) ---------


@pytest.mark.skipif(
    not (PARITY_EVENTSET.is_dir() and PARITY_DIGESTS.is_file()),
    reason="the parity fixture is only in a repository checkout",
)
@pytest.mark.parametrize("kind", ["heteroscedastic", "homoscedastic"])
def test_parity_fixture_matches_thesis_digest(kind: NoiseKind) -> None:
    golden = json.loads(PARITY_DIGESTS.read_text(encoding="utf-8"))
    params = golden["parameters"]
    eventset = EventSet.from_parquet(PARITY_EVENTSET)
    noisy = add_noise(
        eventset,
        level=params["noise_level"],
        kind=kind,
        n_copies=params["noise_reshuffel"],
        rng=np.random.default_rng(params["random_seed"]),
        bounds=tuple(params["heteroscedastic_bounds"]),
        location_ids=params["asset_order"],
    )
    entry = golden["digests"][kind]
    assert list(noisy.loss.shape) == entry["shape"]
    # The bits depend on numpy's exp/log for the CPU and build, so CI compares
    # a summary at rtol 1e-12; the SHA256 only where the digests were written.
    summary = entry["summary"]
    rows, columns, values = zip(*summary["samples"], strict=True)
    actual = np.concatenate(
        [noisy.loss.sum(axis=0), noisy.loss[list(rows), list(columns)]]
    )
    expected = np.array([*summary["column_sums"], *values])
    deviation = np.max(np.abs(actual - expected) / np.abs(expected))
    assert deviation <= 1e-12, f"max relative deviation {deviation:.3e}"
    made = golden["generated_with"]
    if (made["system"], made["machine"], made["numpy"]) == (
        platform.system(),
        platform.machine(),
        np.__version__,
    ):
        data = np.ascontiguousarray(noisy.loss, dtype="<f8").tobytes()
        assert hashlib.sha256(data).hexdigest() == entry["loss_sha256"]
