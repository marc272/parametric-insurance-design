"""Smoke tests of the runnable examples (ADR 0004, Q6).

Each example runs as a reader would run it: a fresh Python process, from a
working directory outside the repository for the two story scripts (the
quickstart reads the fixture by a path relative to the repository root, as
the README shows it). ``TMPDIR`` points at the test's own temporary directory,
so the scripts' new temporary directories land there, and ``MPLBACKEND=Agg``
keeps matplotlib headless.

The printed output is checked against the publication rule: it states the
setup (portfolio, basis-risk model, basis, pricing, split), labels train
values as in-sample, and makes no comparative claim.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parent
REPO_ROOT = EXAMPLES.parent
SCRIPTS = sorted(p.name for p in EXAMPLES.glob("*.py") if p.name != Path(__file__).name)
FIGURES = {
    "tail_risk_objective.py": {"payout_grid_individual", "exceedance_individual"},
    "portfolio_calibration.py": {
        "payout_grid_individual",
        "payout_grid_portfolio",
        "payout_grid_cluster",
    },
}
N_RUNS = {"tail_risk_objective.py": 3, "portfolio_calibration.py": 9}
SETUP_ITEMS = ("portfolio", "basis-risk model", "basis", "pricing", "split")
# Wording that ranks designs or scopes, or points at the project's tracker.
NOT_ALLOWED = re.compile(
    r"\b(better|worse|best|outperform\w*|beats?|wins?|superior|inferior|improve\w*"
    r"|advantage\w*|lower than|higher than|more robust)\b|linear\.app|\bMAR-\d+",
    re.IGNORECASE,
)
ALLOWED_PACKAGES = {"parametric_insurance_design", "parametric_insurance_design_viz"}
STDLIB_AND_PLOTTING = {"tempfile", "pathlib", "matplotlib"}


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[str, Path]]:
    """Run every example once: its stdout and its ``TMPDIR``."""
    out: dict[str, tuple[str, Path]] = {}
    for script in SCRIPTS:
        tmp = tmp_path_factory.mktemp(script.removesuffix(".py"))
        cwd = REPO_ROOT if script == "quickstart.py" else tmp
        done = subprocess.run(
            [sys.executable, str(EXAMPLES / script)],
            cwd=cwd,
            env={**os.environ, "MPLBACKEND": "Agg", "TMPDIR": str(tmp)},
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        assert done.returncode == 0, f"{script} failed:\n{done.stderr}"
        out[script] = (done.stdout, tmp)
    return out


@pytest.mark.parametrize("script", SCRIPTS)
def test_the_output_states_the_setup_and_makes_no_comparative_claim(
    runs: dict[str, tuple[str, Path]], script: str
) -> None:
    stdout, _ = runs[script]
    assert NOT_ALLOWED.search(stdout) is None, NOT_ALLOWED.search(stdout)
    assert "nan" not in stdout.lower()
    assert "annual" in stdout
    assert "out of sample" in stdout
    if script != "quickstart.py":
        for item in SETUP_ITEMS:
            assert re.search(rf"^  {re.escape(item)} ", stdout, re.MULTILINE), item


@pytest.mark.parametrize("script", sorted(N_RUNS))
def test_a_story_prints_test_kpis_and_labels_train_kpis_in_sample(
    runs: dict[str, tuple[str, Path]], script: str
) -> None:
    stdout, _ = runs[script]
    assert stdout.count(" test (out of sample) ") == N_RUNS[script]
    assert stdout.count(" train (in sample) ") == N_RUNS[script]
    rows = [line for line in stdout.splitlines() if "sample) " in line]
    assert all(re.search(r"\d$", row) for row in rows)


@pytest.mark.parametrize("script", sorted(FIGURES))
def test_a_story_writes_its_figures_to_a_new_temporary_directory(
    runs: dict[str, tuple[str, Path]], script: str
) -> None:
    stdout, tmp = runs[script]
    (out,) = tmp.iterdir()  # the working directory got nothing else
    assert stdout.rstrip().endswith(str(out))
    assert (out / "store").is_dir()
    images = {p.stem for p in out.glob("*.png")}
    assert images == FIGURES[script]
    assert all((out / f"{name}.csv").is_file() for name in images)


@pytest.mark.parametrize("script", SCRIPTS)
def test_an_example_imports_only_the_public_api_of_core_and_viz(script: str) -> None:
    tree = ast.parse((EXAMPLES / script).read_text(encoding="utf-8"))
    modules = [
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    ]
    modules += [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    for module in modules:
        parts = module.split(".")
        assert parts[0] in ALLOWED_PACKAGES | STDLIB_AND_PLOTTING, module
        assert not any(p.startswith("_") for p in parts), module
        assert not {"noise", "robust"} & set(parts), module


@pytest.mark.parametrize(
    "probe",
    [
        "import parametric_insurance_design_crc",
        "from parametric_insurance_design_climada import x",
    ],
)
def test_ruff_bans_the_adapters_in_examples(probe: str) -> None:
    pytest.importorskip("ruff", reason="ruff is in the workspace's lint group")
    ruff = [sys.executable, "-m", "ruff", "check", "--select", "TID251", "--no-cache"]
    done = subprocess.run(
        [*ruff, "--stdin-filename", str(EXAMPLES / "probe.py"), "-"],
        input=probe + "\n",
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 1, done.stdout + done.stderr
    assert "TID251" in done.stdout
