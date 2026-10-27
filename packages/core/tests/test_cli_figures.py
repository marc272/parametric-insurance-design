"""Tests of the ``figures`` subcommand (MAR-110).

The core never depends on the viz package: ``figures`` imports it lazily and
raises :class:`~parametric_insurance_design.cli.VizNotInstalledError` without
it. The end-to-end tests need the viz package and skip without it (the core's
Python 3.11 CI job installs the core alone).
"""

from __future__ import annotations

import importlib
import json
import logging
import subprocess
import sys
from importlib.metadata import requires
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from parametric_insurance_design import cli
from parametric_insurance_design.cli import (
    VIZ_DISTRIBUTION,
    VIZ_MODULE,
    ExitCode,
    VizNotInstalledError,
    main,
)
from parametric_insurance_design.errors import ParametricInsuranceDesignError
from parametric_insurance_design.eventset import EventSet

VIZ_PACKAGE = "parametric_insurance_design_viz"


def toy_config(directory: Path, eventset: EventSet, **changes: Any) -> Path:  # noqa: ANN401
    eventset.to_parquet(directory / "eventset")
    data: dict[str, Any] = {
        "schema_version": 1,
        "name": "toy",
        "eventset": {"path": "eventset"},
        "basis": "event_conditional",
        "payout": {"attachment": 20.0, "limit": 60.0, "n_bins": 2},
        "scopes": [{"kind": "individual"}, {"kind": "portfolio"}],
        "objectives": [
            {"kind": "mse"},
            {"kind": "weighted_cvar", "alpha": 0.5, "beta": 0.5},
        ],
        "constraints": [{"kind": "budget", "loading": 1.0}],
        "evaluation": {"beta": 0.5},
        "output": {"directory": "results"},
    }
    data.update(changes)
    path = directory / "toy.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


@pytest.fixture
def config(tmp_path: Path, toy_eventset: EventSet) -> Path:
    return toy_config(tmp_path, toy_eventset)


def without_viz(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the viz package unimportable, as if it were not installed."""
    for name in list(sys.modules):
        if name == VIZ_PACKAGE or name.startswith(f"{VIZ_PACKAGE}."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, VIZ_PACKAGE, None)


# -- the core does not depend on viz -------------------------------------------


def test_core_declares_no_viz_dependency() -> None:
    names = [
        r.split(";")[0].strip() for r in requires("parametric-insurance-design") or []
    ]
    assert not [n for n in names if n.startswith(VIZ_DISTRIBUTION)]


def test_core_does_not_import_viz_at_module_level() -> None:
    code = (
        "import sys\n"
        "import parametric_insurance_design\n"
        "from parametric_insurance_design import cli\n"
        "cli.build_parser().parse_args(['figures', 'x.yaml'])\n"
        f"assert not [m for m in sys.modules if m.startswith({VIZ_PACKAGE!r})], "
        "sorted(m for m in sys.modules if 'viz' in m)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr


def test_viz_module_names_the_viz_package() -> None:
    assert VIZ_MODULE.split(".")[0] == VIZ_PACKAGE
    assert VIZ_DISTRIBUTION == VIZ_PACKAGE.replace("_", "-")


# -- the lazy import ----------------------------------------------------------------


def test_missing_viz_raises_a_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    without_viz(monkeypatch)
    with pytest.raises(VizNotInstalledError, match=VIZ_DISTRIBUTION) as info:
        cli._import_viz()
    assert isinstance(info.value, ParametricInsuranceDesignError)
    assert isinstance(info.value, ImportError)
    assert info.value.name == VIZ_PACKAGE
    assert "pip install parametric-insurance-design-viz" in str(info.value)


def test_missing_viz_dependency_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(name: str) -> object:
        raise ModuleNotFoundError("No module named 'matplotlib'", name="matplotlib")

    monkeypatch.setattr(importlib, "import_module", fail)
    with pytest.raises(VizNotInstalledError, match="dependency 'matplotlib'") as info:
        cli._import_viz()
    assert info.value.name == "matplotlib"


def test_figures_without_viz_exits_3(
    config: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    without_viz(monkeypatch)
    with caplog.at_level(logging.ERROR, logger="parametric_insurance_design"):
        assert main(["figures", str(config)]) == ExitCode.INPUT_ERROR
    assert "VizNotInstalledError" in caplog.text
    assert VIZ_DISTRIBUTION in caplog.text
    assert not (config.parent / "results").exists()


def test_figures_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["figures", "--help"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert "--out DIR" in out
    assert "Never solves" in out
    assert main(["--help"]) == ExitCode.OK
    assert "figures" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["figures"],
        ["figures", "x.yaml", "--policy", "fast"],
        ["figures", "x", "-v", "-q"],
    ],
)
def test_figures_usage_errors(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv) == ExitCode.USAGE
    assert "usage:" in capsys.readouterr().err


# -- end to end (needs viz) ------------------------------------------------------


@pytest.fixture
def viz() -> None:
    pytest.importorskip(VIZ_MODULE)


@pytest.mark.usefixtures("viz")
def test_figures_writes_the_payout_figures(
    config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["run", str(config), "-q"]) == ExitCode.OK
    capsys.readouterr()
    assert main(["figures", str(config), "-q"]) == ExitCode.OK
    out = capsys.readouterr().out
    figures = config.parent / "results" / "figures"
    names = [
        "payout_grid_individual",
        "normalised_payout_individual_a",
        "payout_grid_portfolio",
        "normalised_payout_portfolio_a",
    ]
    for name in names:
        assert (figures / f"{name}.png").is_file()
        assert (figures / f"{name}.csv").is_file()
        assert f"wrote   {name}.png" in out
    assert "5 figures written, 0 skipped" in out  # and premium_reallocation (MAR-112)


@pytest.mark.usefixtures("viz")
def test_figures_out_dir_and_policy(
    config: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["run", str(config), "-q", "--policy", "thesis"]) == ExitCode.OK
    out_dir = tmp_path / "elsewhere"
    # the default-policy runs are not in the store
    assert main(["figures", str(config), "--out", str(out_dir)]) == ExitCode.INPUT_ERROR
    assert not out_dir.exists()
    args = ["figures", str(config), "--out", str(out_dir), "--policy", "thesis"]
    assert main(args) == ExitCode.OK
    assert (out_dir / "payout_grid_portfolio.png").is_file()
    assert not (config.parent / "results" / "figures").exists()
    capsys.readouterr()


@pytest.mark.usefixtures("viz")
def test_figures_before_run_is_an_input_error(
    config: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="parametric_insurance_design"):
        assert main(["figures", str(config)]) == ExitCode.INPUT_ERROR
    assert "MissingRunError" in caplog.text
    assert "parametric-insurance-design run CONFIG" in caplog.text


@pytest.mark.usefixtures("viz")
def test_figures_of_a_failed_run_exit_1(
    tmp_path: Path, toy_eventset: EventSet, capsys: pytest.CaptureFixture[str]
) -> None:
    cluster = {
        "kind": "cluster",
        "n_clusters": 3,  # two locations: a build failure
        "strategy": {"kind": "thesis_ward", "beta_tail": 0.5},
    }
    path = toy_config(tmp_path, toy_eventset, scopes=[{"kind": "portfolio"}, cluster])
    assert main(["run", str(path), "-q"]) == ExitCode.RUNS_FAILED
    capsys.readouterr()
    assert main(["figures", str(path), "-q"]) == ExitCode.RUNS_FAILED
    out = capsys.readouterr().out
    assert "FAILED  payout_grid_cluster" in out
    assert "(2 because a run failed)" in out
    written = sorted(p.name for p in (tmp_path / "results" / "figures").glob("*.png"))
    assert written == ["normalised_payout_portfolio_a.png", "payout_grid_portfolio.png"]
    manifest = json.loads(
        next((tmp_path / "results" / "manifests").glob("*.json")).read_text()
    )
    assert manifest["format"]  # the store is untouched by figures


# -- sweep points (MAR-112) ----------------------------------------------------


@pytest.mark.usefixtures("viz")
def test_figures_reads_the_sweep_points(
    tmp_path: Path, toy_eventset: EventSet, capsys: pytest.CaptureFixture[str]
) -> None:
    sweeps = [{"parameter": "alpha", "values": [0.3, 0.5]}]
    path = toy_config(tmp_path, toy_eventset, sweeps=sweeps)
    assert main(["sweep", str(path), "-q"]) == ExitCode.OK
    capsys.readouterr()
    assert main(["figures", str(path), "-q"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert "read 4 sweep points of 1 sweeps" in out  # 2 values x 2 scopes
    figures = tmp_path / "results" / "figures"
    for name in (
        "premium_reallocation",
        "payout_sweep_individual_a_alpha",
        "payout_sweep_portfolio_a_alpha",
        "sensitivity_alpha",
        "tradeoff_portfolio_alpha",
    ):
        assert (figures / f"{name}.png").is_file(), name
        assert f"wrote   {name}.png" in out
    points = pd.read_csv(figures / "sensitivity_alpha.points.csv")
    assert set(points["parameter_value"].dropna()) == {0.3, 0.5}


@pytest.mark.usefixtures("viz")
def test_missing_sweep_points_name_the_sweep_command(
    tmp_path: Path, toy_eventset: EventSet, caplog: pytest.LogCaptureFixture
) -> None:
    sweeps = [{"parameter": "alpha", "values": [0.3]}]
    path = toy_config(tmp_path, toy_eventset, sweeps=sweeps)
    assert main(["run", str(path), "-q"]) == ExitCode.OK
    with caplog.at_level(logging.ERROR, logger="parametric_insurance_design"):
        assert main(["figures", str(path)]) == ExitCode.INPUT_ERROR
    assert "2 of 2 sweep points are not in the result store" in caplog.text
    assert "parametric-insurance-design sweep CONFIG" in caplog.text
