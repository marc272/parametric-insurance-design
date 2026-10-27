#!/usr/bin/env bash
# Negative test for the package import boundaries (MAR-76).
#
# The boundaries (AGENTS.md "Hard boundaries", ADR 0001) are enforced by ruff's
# TID251 (flake8-tidy-imports banned-api), configured in the [tool.ruff] table
# of packages/core, packages/viz and packages/climada/pyproject.toml. Each of
# those extends the root config, so the CI `ruff check` (job lint) applies the
# bans to every file under the package, src, tests and scripts alike.
#
# This script proves the bans fire, so that a config change that silently
# drops one fails CI: it pipes a probe module through `ruff check` as if it
# were a file at the given path (--stdin-filename; nothing is written) and
# expects TID251 for every forbidden import and no TID251 for the allowed
# ones, including the core's one sanctioned dynamic route to viz.
#
# Usage: scripts/check_import_boundaries.sh   (from anywhere in the checkout;
#        CI runs it as `uv run --locked scripts/check_import_boundaries.sh`)
# Exit status: 0 if every case behaves as expected, 1 otherwise.
#
# Runs under macOS's /bin/bash 3.2.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
ruff=${RUFF:-ruff}

core=packages/core/src/parametric_insurance_design/_probe.py
core_test=packages/core/tests/test_probe.py
viz=packages/viz/src/parametric_insurance_design_viz/_probe.py
viz_test=packages/viz/tests/test_probe.py
climada=packages/climada/src/parametric_insurance_design_climada/_probe.py
climada_test=packages/climada/tests/test_probe.py
climada_script=packages/climada/scripts/probe.py
crc=packages/crc/src/parametric_insurance_design_crc/_probe.py

# expect|path|probe source (\n separates lines)
cases="ban|$core|import parametric_insurance_design_viz
ban|$core|from parametric_insurance_design_viz.command import write_figures
ban|$core|import parametric_insurance_design_crc
ban|$core|import parametric_insurance_design_crc.sub as crc
ban|$core|def f() -> None:\n    from parametric_insurance_design_climada import tracks\n    del tracks
ban|$core|from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import parametric_insurance_design_viz
ban|$core_test|from parametric_insurance_design_viz import command
ban|$core_test|import parametric_insurance_design_climada
ban|$viz|import parametric_insurance_design_crc
ban|$viz|from parametric_insurance_design_climada.pipeline import build_eventset
ban|$viz_test|import parametric_insurance_design_climada
ban|$viz_test|from parametric_insurance_design_crc import x
ban|$climada|import parametric_insurance_design_crc
ban|$climada|from parametric_insurance_design_crc.sub import x
ban|$climada_test|import parametric_insurance_design_crc
ban|$climada_script|from parametric_insurance_design_crc import x
ok|$core|import importlib\nviz = importlib.import_module(\"parametric_insurance_design_viz.command\")
ok|$core|import parametric_insurance_design.solve
ok|$viz|import parametric_insurance_design
ok|$climada|import parametric_insurance_design
ok|$climada|from parametric_insurance_design_climada import tracks
ok|$crc|import parametric_insurance_design"

fail=0
n=0
while IFS='|' read -r expect path source; do
  n=$((n + 1))
  dir=$(dirname "$path")
  if [ ! -d "$dir" ]; then
    echo "FAIL [$expect] $path: directory $dir is missing; update this script"
    fail=1
    continue
  fi
  out=$(printf '"""Probe."""\n\n%b\n' "$source" |
    "$ruff" check --no-cache --output-format=concise --stdin-filename "$path" - 2>&1)
  if echo "$out" | grep -q 'TID251'; then got=ban; else got=ok; fi
  shown=$(printf '%b' "$source" | tr '\n' ';')
  if [ "$got" = "$expect" ]; then
    echo "ok   [$expect] $path: $shown"
  else
    echo "FAIL [$expect, got $got] $path: $shown"
    echo "$out" | sed 's/^/    /'
    fail=1
  fi
done <<EOF
$cases
EOF

if [ $fail -eq 0 ]; then
  echo "check_import_boundaries: all $n cases as expected"
else
  echo "check_import_boundaries: FAILED (see above)"
fi
exit $fail
