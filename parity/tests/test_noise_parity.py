"""Bit-identical parity of the noise layer with the thesis (MAR-10, F-06).

Two groups:

- Against the committed digests in ``parity/golden/noise_digests.json``,
  which ``parity/scripts/thesis_noise_digests.py`` wrote from the thesis
  function. They need nothing outside this repository. The SHA256 of the
  noisy losses is checked only on the platform that wrote it (numpy's
  ``exp``/``log`` bits depend on the CPU and build); a summary (column sums
  and sampled entries, rtol 1e-12) is checked everywhere.
- Against the thesis function itself, ``add_noise_to_asset_losses``. It is
  loaded from ``src/utils/data_processing.py`` of the thesis checkout in
  ``PARITY_THESIS_REPO`` on its own (that file imports only numpy and pandas),
  so no thesis dependency is needed. Skipped, with that reason, if the
  variable is not set.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.noise import NoiseKind, add_noise

PARITY_DIR = Path(__file__).resolve().parents[1]
SCRIPT = PARITY_DIR / "scripts" / "thesis_noise_digests.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("thesis_noise_digests", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


nd = _load_script()


@pytest.fixture(scope="module")
def eventset() -> EventSet:
    return EventSet.from_parquet(nd.EVENTSET_DIR)


@pytest.fixture(scope="module")
def digests() -> dict:
    return json.loads(nd.DIGESTS.read_text(encoding="utf-8"))


def _port(eventset: EventSet, kind: NoiseKind, seed: int = nd.SEED) -> EventSet:
    return add_noise(
        eventset,
        level=nd.LEVEL,
        kind=kind,
        n_copies=nd.N_COPIES,
        rng=np.random.default_rng(seed),
        bounds=nd.BOUNDS,
    )


@pytest.fixture(scope="module")
def ported(eventset: EventSet) -> dict[str, EventSet]:
    return {kind: _port(eventset, kind) for kind in nd.KINDS}


# -- committed digests (no thesis repository needed) --------------------------


def test_digest_file_describes_this_fixture(digests: dict) -> None:
    params = digests["parameters"]
    assert (params["random_seed"], params["noise_level"]) == (42, 0.3)
    assert params["noise_reshuffel"] == 13
    assert params["heteroscedastic_bounds"] == [20.0, 70.0]
    assert params["asset_order"] == [f"A{k}" for k in range(1, 10)]
    for name, digest in digests["eventset"]["files_sha256"].items():
        assert nd.sha256_file(nd.EVENTSET_DIR / name) == digest, name
    assert sorted(digests["digests"]) == sorted(nd.KINDS)


@pytest.mark.parametrize("kind", nd.KINDS)
def test_noisy_losses_match_thesis_summary(
    kind: str, ported: dict[str, EventSet], digests: dict
) -> None:
    # Cross-platform check: column sums and sampled entries at rtol 1e-12.
    noisy = ported[kind]
    entry = digests["digests"][kind]
    assert list(noisy.loss.shape) == entry["shape"]
    deviation = nd.summary_deviation(entry["summary"], noisy.loss)
    assert deviation <= nd.SUMMARY_RTOL, f"max relative deviation {deviation:.3e}"


@pytest.mark.parametrize("kind", nd.KINDS)
def test_noisy_losses_match_thesis_digest(
    kind: str, ported: dict[str, EventSet], digests: dict
) -> None:
    # Bit-level check: only on the platform that wrote the digests, because
    # numpy's exp/log bits depend on the CPU and the numpy build.
    if not nd.same_platform(digests):
        made = digests["generated_with"]
        pytest.skip(
            "bitwise digest was written on "
            f"{made['system']} {made['machine']} with numpy {made['numpy']}; "
            "the summary test covers this platform"
        )
    assert (
        nd.matrix_digest(ported[kind].loss) == digests["digests"][kind]["loss_sha256"]
    )


def test_thesis_expansion_and_rates(eventset: EventSet, ported: dict) -> None:
    noisy = ported[nd.THESIS_KIND]
    n = nd.N_COPIES
    assert noisy.n_rows == n * eventset.n_rows == 78_741
    events = noisy.events
    np.testing.assert_array_equal(
        events["event_id"], np.repeat(eventset.events["event_id"].to_numpy(), n)
    )
    np.testing.assert_array_equal(
        events["draw_id"], np.tile(np.arange(n), eventset.n_rows)
    )
    # Thesis: probability = 1 / (Y * noise_reshuffel) on every row.
    expected_rate = 1.0 / (eventset.metadata.n_years * n)
    assert (noisy.rates == expected_rate).all()
    assert noisy.rates.sum() == pytest.approx(eventset.rates.sum(), rel=1e-12)
    np.testing.assert_array_equal(noisy.index, np.repeat(eventset.index, n, axis=0))
    assert noisy.metadata.filters == ()
    # MAR-88: the noise parameters are a structured record, not scenario text.
    assert noisy.metadata.scenario == eventset.metadata.scenario
    (record,) = noisy.metadata.transforms
    assert record.name == "noise"
    assert record.n_filters_before == 0
    assert record.parameters["kind"] == "heteroscedastic"
    assert (record.parameters["level"], record.parameters["n_copies"]) == (0.3, 13)


def test_other_seed_differs(eventset: EventSet, digests: dict) -> None:
    other = _port(eventset, nd.THESIS_KIND, seed=43)
    summary = digests["digests"][nd.THESIS_KIND]["summary"]
    assert nd.summary_deviation(summary, other.loss) > 1e-3


# -- against the thesis function (local only) ---------------------------------


@pytest.fixture(scope="module")
def thesis_repo() -> Path:
    value = os.environ.get(nd.THESIS_REPO_ENV)
    if not value:
        pytest.skip(
            f"{nd.THESIS_REPO_ENV} is not set; set it to a checkout of the "
            "thesis repository to run the original add_noise_to_asset_losses"
        )
    repo = Path(value).expanduser()
    if not (repo / nd.THESIS_MODULE).is_file():
        pytest.fail(f"{nd.THESIS_REPO_ENV}={value} does not hold {nd.THESIS_MODULE}")
    return repo


@pytest.fixture(scope="module")
def thesis_module(thesis_repo: Path) -> ModuleType:
    return nd.load_thesis_module(thesis_repo)


@pytest.fixture(scope="module")
def thesis_output(thesis_module: ModuleType, eventset: EventSet) -> dict:
    return {kind: nd.run_thesis(thesis_module, eventset, kind) for kind in nd.KINDS}


def test_thesis_module_is_the_recorded_one(thesis_repo: Path, digests: dict) -> None:
    assert (
        nd.sha256_file(thesis_repo / nd.THESIS_MODULE)
        == digests["thesis_module_sha256"]
    )


def test_thesis_config_matches_parameters(thesis_repo: Path) -> None:
    yaml = pytest.importorskip("yaml")
    settings = yaml.safe_load(
        (thesis_repo / "configs/global_settings.yaml").read_text()
    )
    experiment = yaml.safe_load(
        (thesis_repo / "configs/experiment_config.yaml").read_text()
    )
    assert settings["RANDOM_SEED"] == nd.SEED
    assert (settings["ATTACHEMENT"], settings["LIMIT"]) == nd.BOUNDS
    noise = experiment["NOISE_LAYER"]
    assert (noise["noise_value"], noise["noise_type"], noise["reshuffel"]) == (
        nd.LEVEL,
        nd.THESIS_KIND,
        nd.N_COPIES,
    )
    assert list(experiment["ASSETS"]) == [f"A{k}" for k in range(1, 10)]


@pytest.mark.parametrize("kind", nd.KINDS)
def test_bit_identical_to_thesis_function(
    kind: str, thesis_output: dict, ported: dict[str, EventSet], eventset: EventSet
) -> None:
    thesis = thesis_output[kind]
    noisy = ported[kind]
    ids = eventset.location_ids
    # Noisy losses: bit for bit.
    thesis_loss = nd.thesis_losses(thesis, ids)
    assert np.array_equal(noisy.loss, thesis_loss)
    assert nd.matrix_digest(thesis_loss) == nd.matrix_digest(noisy.loss)
    # Expansion: same rows in the same order, draw_id = noise_sample_id.
    np.testing.assert_array_equal(noisy.events["event_id"], thesis["Event_ID"])
    np.testing.assert_array_equal(noisy.events["year"], thesis["Year"])
    np.testing.assert_array_equal(noisy.events["draw_id"], thesis["noise_sample_id"])
    winds = thesis[[f"{loc}_Wind" for loc in ids]].to_numpy()
    assert np.array_equal(noisy.index, winds)


def test_thesis_function_reproduces_committed_digests(
    thesis_output: dict, eventset: EventSet, digests: dict
) -> None:
    for kind in nd.KINDS:
        losses = nd.thesis_losses(thesis_output[kind], eventset.location_ids)
        entry = digests["digests"][kind]
        assert nd.summary_deviation(entry["summary"], losses) <= nd.SUMMARY_RTOL
        if nd.same_platform(digests):
            assert nd.matrix_digest(losses) == entry["loss_sha256"]


def test_rates_match_thesis_probabilities(
    thesis_module: ModuleType, thesis_output: dict, ported: dict, eventset: EventSet
) -> None:
    thesis = thesis_module.calculate_annual_event_probabilities(
        thesis_output[nd.THESIS_KIND], eventset.metadata.n_years, nd.N_COPIES
    )
    assert np.array_equal(ported[nd.THESIS_KIND].rates, thesis["probability"])


def test_thesis_notebook_pipeline_from_csv(
    thesis_repo: Path, thesis_module: ModuleType, ported: dict, eventset: EventSet
) -> None:
    # The notebook path: load the CSV, take the sub-portfolio, add noise.
    raw = pd.read_csv(thesis_repo / "data/output/climada_transformed_loss_data.csv")
    ids = eventset.location_ids
    frame = thesis_module.create_sub_portfolio(raw, ids)
    thesis = thesis_module.add_noise_to_asset_losses(
        df=frame,
        asset_data=ids,
        noise_level=nd.LEVEL,
        noise_type=nd.THESIS_KIND,
        random_seed=nd.SEED,
        noise_reshuffel=nd.N_COPIES,
    )
    assert np.array_equal(ported[nd.THESIS_KIND].loss, nd.thesis_losses(thesis, ids))
