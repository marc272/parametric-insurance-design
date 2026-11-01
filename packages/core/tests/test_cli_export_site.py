"""Tests of the ``export-site`` subcommand (MAR-200).

Like ``figures``, ``export-site`` imports the viz package lazily and raises
:class:`~parametric_insurance_design.cli.VizNotInstalledError` without it.
The end-to-end tests run on the thesis parity event set
(``parity/tests/data/thesis_eventset``) with a small config, need the viz
package and skip without it (the core's Python 3.11 CI job installs the core
alone). They read the bundle back with :mod:`json`, :mod:`hashlib` and
pyarrow only.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
import yaml

from parametric_insurance_design import cli
from parametric_insurance_design.cli import (
    EXPORT_MODULE,
    VIZ_DISTRIBUTION,
    ExitCode,
    VizNotInstalledError,
    main,
)
from parametric_insurance_design.experiment.config import config_hash, load_config
from parametric_insurance_design.experiment.runner import load_input, run_key

VIZ_PACKAGE = "parametric_insurance_design_viz"
FIXTURE = Path(__file__).resolve().parents[3] / "parity/tests/data/thesis_eventset"
FIXTURE_CHECKSUM = (
    "sha256:404b0c3a3aefa38965ad3ace2747d308685a67e3b218cb835d45a9ab375294df"
)


def parity_config(directory: Path, **changes: Any) -> Path:  # noqa: ANN401
    """A small config on the thesis parity event set (no noise, 5 bins)."""
    data: dict[str, Any] = {
        "schema_version": 1,
        "name": "parity-site",
        "description": "export-site test on the thesis parity event set",
        "eventset": {"path": str(FIXTURE), "checksum": FIXTURE_CHECKSUM},
        "portfolio": {"location_ids": ["A1", "A2", "A3"]},
        "threshold": {"value": 20.0, "column": "index"},
        "basis": "event_conditional",
        "payout": {"attachment": 20.0, "limit": 70.0, "n_bins": 5},
        "scopes": [{"kind": "individual"}, {"kind": "portfolio"}],
        "objectives": [
            {"kind": "mse"},
            {"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.95},
        ],
        "constraints": [{"kind": "budget", "loading": 1.0}],
        "evaluation": {"beta": 0.95},
        "sweeps": [
            {"parameter": "alpha", "values": [0.5, 0.9]},
            {"parameter": "n_assets", "values": [2], "max_combinations": 1, "seed": 0},
        ],
        "output": {"directory": "results"},
    }
    data.update(changes)
    path = directory / "parity-site.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def without_viz(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the viz package unimportable, as if it were not installed."""
    for name in list(sys.modules):
        if name == VIZ_PACKAGE or name.startswith(f"{VIZ_PACKAGE}."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, VIZ_PACKAGE, None)


def sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


# -- the lazy import ------------------------------------------------------------------


def test_export_module_names_the_viz_package() -> None:
    assert EXPORT_MODULE == f"{VIZ_PACKAGE}.site_export"


def test_parsing_export_site_does_not_import_viz() -> None:
    code = (
        "import sys\n"
        "from parametric_insurance_design import cli\n"
        "cli.build_parser().parse_args(['export-site', 'x.yaml', '-p', 'alpha'])\n"
        f"assert not [m for m in sys.modules if m.startswith({VIZ_PACKAGE!r})]\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr


def test_missing_viz_raises_a_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    without_viz(monkeypatch)
    with pytest.raises(VizNotInstalledError, match="export-site command") as info:
        cli._import_export()
    assert info.value.name == VIZ_PACKAGE
    assert f"pip install {VIZ_DISTRIBUTION}" in str(info.value)


def test_missing_viz_dependency_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(name: str) -> object:
        raise ModuleNotFoundError("No module named 'pyarrow'", name="pyarrow")

    monkeypatch.setattr(importlib, "import_module", fail)
    with pytest.raises(VizNotInstalledError, match="dependency 'pyarrow'") as info:
        cli._import_export()
    assert info.value.name == "pyarrow"


def test_export_site_without_viz_exits_3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = parity_config(tmp_path)
    without_viz(monkeypatch)
    with caplog.at_level(logging.ERROR, logger="parametric_insurance_design"):
        assert main(["export-site", str(config)]) == ExitCode.INPUT_ERROR
    assert "VizNotInstalledError" in caplog.text
    assert not (tmp_path / "results").exists()


def test_export_site_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["export-site", "--help"]) == ExitCode.OK
    out = capsys.readouterr().out
    for option in (
        "--out DIR",
        "--parameter P",
        "--no-sweeps",
        "--events",
        "--max-file-bytes N",
        "--max-bundle-bytes N",
        "--label TEXT",
    ):
        assert option in out
    assert "Never solves" in out
    assert main(["--help"]) == ExitCode.OK
    assert "export-site" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["export-site"],
        ["export-site", "x.yaml", "--no-sweeps", "-p", "alpha"],
        ["export-site", "x.yaml", "--max-file-bytes", "0"],
        ["export-site", "x.yaml", "--max-bundle-bytes", "many"],
        ["export-site", "x.yaml", "--policy", "fast"],
        ["export-site", "x.yaml", "-v", "-q"],
    ],
)
def test_export_site_usage_errors(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv) == ExitCode.USAGE
    assert "usage:" in capsys.readouterr().err


# -- end to end (needs viz) ---------------------------------------------------------


@pytest.fixture(scope="module")
def solved(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The small parity config, its single runs and its alpha sweep solved."""
    pytest.importorskip(EXPORT_MODULE)
    config = parity_config(tmp_path_factory.mktemp("parity-site"))
    assert main(["sweep", str(config), "-p", "alpha", "-q"]) == ExitCode.OK
    return config


def test_export_site_writes_a_bundle_that_reads_back(
    solved: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    assert main(["export-site", str(solved), "-q"]) == ExitCode.OK
    out = capsys.readouterr().out
    bundle = solved.parent / "results" / "site"
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    config = load_config(solved)
    checksum = load_input(config).checksum
    assert manifest["config"]["hash"] == config_hash(config)
    assert manifest["runs"]["baseline"] == [
        run_key(config_hash(s), checksum) for s in config.single_runs()
    ]
    alpha = [p["value"] for p in manifest["runs"]["sweeps"]["alpha"]]
    assert alpha == [0.5, 0.5, 0.9, 0.9]  # value-major, one per scope
    assert manifest["sweeps_not_exported"] == ["n_assets"]
    assert manifest["label"] == "export-site test on the thesis parity event set"
    assert manifest["setup"]["portfolio"] == {"location_ids": ["A1", "A2", "A3"]}
    names = [f["path"] for f in manifest["files"]]
    assert sorted(p.name for p in bundle.iterdir()) == sorted([*names, "manifest.json"])
    for entry in manifest["files"]:
        path = bundle / entry["path"]
        assert path.stat().st_size == entry["bytes"]
        assert sha256(path) == entry["sha256"]
        assert f"wrote   {entry['path']}  ({entry['bytes']:,} bytes)" in out
        if entry["format"] == "arrow":
            with pa.memory_map(str(path)) as source:
                table = pa.ipc.open_file(source).read_all()
            assert table.num_rows == entry["rows"] > 0
            assert table.column_names == [c["name"] for c in entry["columns"]]
        else:
            json.loads(path.read_text(encoding="utf-8"))
    assert "sweeps not exported: n_assets" in out
    assert "0 runs left out because they failed" in out


def test_export_site_options(
    solved: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_dir = tmp_path / "bundle"
    argv = ["export-site", str(solved), "--out", str(out_dir), "-q"]
    assert main([*argv, "--no-sweeps", "--events", "--label", "fixture"]) == 0
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["label"] == "fixture"
    assert manifest["events"]["included"] is True
    assert (out_dir / "baseline.events.arrow").is_file()
    assert manifest["runs"]["sweeps"] == {}
    capsys.readouterr()
    assert main([*argv, "-p", "alpha"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert "removed baseline.events.arrow" in out
    assert (out_dir / "sweep.alpha.kpis.arrow").is_file()


def test_over_budget_exits_3_and_writes_nothing(
    solved: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    out_dir = tmp_path / "bundle"
    argv = ["export-site", str(solved), "--out", str(out_dir), "-q"]
    with caplog.at_level(logging.ERROR, logger="parametric_insurance_design"):
        assert main([*argv, "--max-file-bytes", "2000"]) == ExitCode.INPUT_ERROR
    assert "BundleBudgetError" in caplog.text
    assert "over the 2,000-byte file budget" in caplog.text
    assert not out_dir.exists()
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="parametric_insurance_design"):
        assert main([*argv, "--max-bundle-bytes", "5000"]) == ExitCode.INPUT_ERROR
    assert "5,000-byte bundle budget" in caplog.text
    assert not out_dir.exists()


def test_a_run_missing_from_the_store_exits_3(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    pytest.importorskip(EXPORT_MODULE)
    config = parity_config(tmp_path)
    with caplog.at_level(logging.ERROR, logger="parametric_insurance_design"):
        assert main(["export-site", str(config), "-q"]) == ExitCode.INPUT_ERROR
    assert "MissingRunError" in caplog.text
    assert not (tmp_path / "results" / "site").exists()


def test_a_missing_sweep_point_exits_3(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    pytest.importorskip(EXPORT_MODULE)
    config = parity_config(tmp_path)
    assert main(["run", str(config), "-q"]) == ExitCode.OK
    with caplog.at_level(logging.ERROR, logger="parametric_insurance_design"):
        assert main(["export-site", str(config), "-q"]) == ExitCode.INPUT_ERROR
    assert "sweep points are not in the result store" in caplog.text
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="parametric_insurance_design"):
        assert main(["export-site", str(config), "-p", "beta"]) == 3
    assert "has no sweep of ['beta']" in caplog.text
    assert main(["export-site", str(config), "--no-sweeps", "-q"]) == ExitCode.OK


def test_failed_runs_exit_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pytest.importorskip(EXPORT_MODULE)
    config = parity_config(
        tmp_path,
        scopes=[
            {"kind": "portfolio"},
            {
                "kind": "cluster",
                "n_clusters": 4,
                "strategy": {"kind": "thesis_ward", "beta_tail": 0.9},
            },
        ],
        objectives=[{"kind": "mse"}],
        sweeps=[],
    )
    assert main(["run", str(config), "-q"]) == ExitCode.RUNS_FAILED
    capsys.readouterr()
    assert main(["export-site", str(config), "-q"]) == ExitCode.RUNS_FAILED
    out = capsys.readouterr().out
    assert "FAILED  sha256:" in out
    assert "1 runs left out because they failed" in out
