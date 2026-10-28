#!/usr/bin/env bash
# Local stand-in for .github/workflows/ci.yml and climada.yml (MAR-116).
#
# The repository has no GitHub Actions minutes (Marc, 2026-10-27), so while
# they are exhausted this script is the merge gate: see docs/ORCHESTRATION.md,
# "Merge policy". Keep its jobs in step with the two workflows.
#
# Usage:
#   scripts/ci_local.sh [--setup] <checkout-dir> [job ...]
#   scripts/ci_local.sh --setup          # only create the Python 3.11 env
#                                        # (always in the main checkout)
#   scripts/ci_local.sh --list           # list the jobs
#
# Jobs (default: all, in this order):
#   lint                     ruff check, import-boundary negative test,
#                            ruff format --check, pyright, ruff single
#                            source check, pre-commit
#   workspace-3.12           core (coverage >= 85 %), viz + crc, parity tests
#   workspace-3.13           the same on Python 3.13
#   core-3.11-highest        core alone on 3.11, newest dependencies
#   core-3.11-lowest-direct  core alone on 3.11, lowest direct dependencies
#   build                    all four wheels, licence metadata (ADR 0001)
#   climada                  pixi: adapter tests, typecheck, core in the CLIMADA env
#
# Python 3.11: uv may not be able to download Pythons, so the core-3.11-* jobs
# use, in order: $CI_LOCAL_PY311 (an error if it is set but not executable);
# the pixi env in scripts/ci_local/py311 (made by --setup), looked up next to
# this script, in the checkout under test, then in the main checkout of a
# linked worktree (found with `git rev-parse --git-common-dir`; MAR-150), so
# agent worktrees use the main checkout's env; any 3.11 that uv finds. The
# start of the output names the Python taken and warns loudly when no pixi env
# was found. With none of these the jobs fall back to 3.12 and say so in the
# summary. On 3.12, core-3.11-lowest-direct cannot install (pandas 2.1.0 has
# no cp312 wheel).
#
# --setup builds the env in the main checkout even when run from a linked
# worktree (MAR-157): the worktrees find it there, and a copy per worktree
# would only duplicate it. It uses the main checkout's pixi.toml and pixi.lock.
#
# Output: one PASS/FAIL line per job, then a summary with the commit. Logs go
# to a fresh temp directory outside the checkout, printed at the start (made
# only once the arguments and CI_LOCAL_PY311 have been checked).
# Exit status: 0 if every job passed, 1 if any failed, 2 on a usage error.
#
# Runs under macOS's /bin/bash 3.2: no associative arrays, no mapfile, and no
# "${arr[@]}" on an empty array under set -u.
set -uo pipefail

here=$(cd "$(dirname "$0")" && pwd)
py311_env_rel="ci_local/py311/.pixi/envs/default/bin/python3.11"
py311_env_python="$here/$py311_env_rel"
all_jobs="lint workspace-3.12 workspace-3.13 core-3.11-highest core-3.11-lowest-direct build climada"

usage() {
  cat <<EOT
usage: scripts/ci_local.sh [--setup] <checkout-dir> [job ...]
       scripts/ci_local.sh --setup | --list | --help
--setup creates the Python 3.11 pixi env in the main checkout, also when run
from a linked worktree; worktrees reuse that env (CI_LOCAL_PY311 overrides).
jobs (default: all): $all_jobs
EOT
}

setup=0
case ${1:-} in
  -h | --help) usage; exit 0 ;;
  --list) printf '%s\n' $all_jobs; exit 0 ;;
  --setup) setup=1; shift ;;
esac

if [ $setup -eq 1 ]; then
  # The main checkout is the parent of the shared .git, also from a linked
  # worktree; outside git, the env goes next to this script.
  setup_scripts=$here
  if common=$(git -C "$here" rev-parse --path-format=absolute --git-common-dir 2>/dev/null); then
    setup_scripts=$(cd "$common/.." && pwd)/scripts || exit 2
  fi
  setup_manifest="$setup_scripts/ci_local/py311/pixi.toml"
  if [ ! -f "$setup_manifest" ]; then
    echo "ci_local: no $setup_manifest; update the main checkout, or set CI_LOCAL_PY311" >&2
    exit 2
  fi
  echo "ci_local: creating the Python 3.11 env from $setup_manifest"
  pixi install --locked --manifest-path "$setup_manifest" || exit 2
  "$setup_scripts/$py311_env_rel" --version || exit 2
  [ $# -eq 0 ] && exit 0
fi

if [ $# -lt 1 ] || [ ! -d "$1" ]; then
  usage >&2
  exit 2
fi
cd "$1" || exit 2
shift
top=$(git rev-parse --show-toplevel) || exit 2
cd "$top" || exit 2

selected="$*"
[ -z "$selected" ] && selected=$all_jobs
for j in $selected; do
  case " $all_jobs " in
    *" $j "*) ;;
    *) echo "ci_local: unknown job '$j' (jobs: $all_jobs)" >&2; exit 2 ;;
  esac
done

head=$(git rev-parse --short HEAD)
branch=$(git rev-parse --abbrev-ref HEAD)
dirty=$(git status --porcelain --untracked-files=normal | wc -l | tr -d ' ')
state="clean tree"
[ "$dirty" != 0 ] && state="DIRTY tree: $dirty changed or untracked paths, not a pure run of the commit"
echo "ci_local: $(pwd), bash $BASH_VERSION, $(uname -sm)"
echo "ci_local: $head on $branch ($state)"

# The Python of the core-3.11-* jobs, resolved once (see the header) and
# named in the output: a path, or "3.11" for uv's own lookup.
find_py311() {
  local common main candidate looked=""
  if [ -n "${CI_LOCAL_PY311:-}" ]; then
    if [ ! -x "$CI_LOCAL_PY311" ]; then
      echo "ci_local: CI_LOCAL_PY311=$CI_LOCAL_PY311 is not an executable" >&2
      return 1
    fi
    py311=$CI_LOCAL_PY311
    echo "ci_local: python 3.11 for core-3.11-*: $py311 (CI_LOCAL_PY311)"
    return 0
  fi
  # The main checkout of a linked worktree is the parent of the shared .git.
  common=$(git rev-parse --git-common-dir) || return 1
  main=$(cd "$common/.." && pwd) || return 1
  for candidate in "$py311_env_python" "$top/scripts/$py311_env_rel" \
    "$main/scripts/$py311_env_rel"; do
    if [ -x "$candidate" ]; then
      py311=$candidate
      echo "ci_local: python 3.11 for core-3.11-*: $py311 (pixi env)"
      return 0
    fi
    case "$looked " in
      *" $candidate "*) ;;
      *) looked="$looked $candidate" ;;
    esac
  done
  py311=3.11
  echo "ci_local: WARNING: no pixi Python 3.11 env found. Looked for:"
  for candidate in $looked; do
    echo "ci_local: WARNING:   $candidate"
  done
  echo "ci_local: WARNING: the core-3.11-* jobs take any 3.11 uv finds, else"
  echo "ci_local: WARNING: Python 3.12, where core-3.11-lowest-direct fails."
  echo "ci_local: WARNING: run scripts/ci_local.sh --setup (it builds the env in"
  echo "ci_local: WARNING: the main checkout, also from a worktree), or set CI_LOCAL_PY311."
}

py311=""
case " $selected " in
  *" core-3.11-"*) find_py311 || exit 2 ;;
esac

# After every check that can exit 2, so a usage error leaves no empty log dir.
tmp=${TMPDIR:-/tmp}
logdir=$(mktemp -d "${tmp%/}/ci-local.XXXXXX") || exit 2
echo "ci_local: logs in $logdir"

fail=0
results=""
started=$SECONDS

run_job() {
  local name=$1
  shift
  local log="$logdir/$name.log"
  local start=$SECONDS line
  # A job function may write a one-line note (e.g. the Python it used) here.
  export CI_LOCAL_NOTE="$logdir/$name.note"
  # Not inside `if`: errexit is ignored in a condition context, and every job
  # relies on set -e to stop at its first failing step.
  (set -e; "$@") >"$log" 2>&1
  local rc=$?
  if [ $rc -eq 0 ]; then
    line="PASS $name ($((SECONDS - start)) s)"
  else
    line="FAIL $name ($((SECONDS - start)) s, exit $rc) -> $log"
    fail=1
  fi
  [ -s "$CI_LOCAL_NOTE" ] && line="$line [$(cat "$CI_LOCAL_NOTE")]"
  results="$results$line
"
  echo "$line"
}

job_lint() {
  uv sync --locked
  uv run --locked ruff check
  uv run --locked scripts/check_import_boundaries.sh
  uv run --locked ruff format --check
  uv run --locked pyright
  uv run --locked scripts/check_ruff_single_source.py --self-test
  uv run --locked pre-commit run --all-files --show-diff-on-failure
}

job_workspace() {
  local py=$1
  # A venv per Python, so the two jobs don't rebuild each other's (and the
  # default .venv) every run. .venv-*/ is git-ignored.
  export UV_PROJECT_ENVIRONMENT=".venv-ci-$py"
  uv sync --locked --python "$py"
  uv run --locked --python "$py" python --version
  uv run --locked --python "$py" pytest packages/core/tests \
    --cov=parametric_insurance_design --cov-report=term-missing --cov-fail-under=85
  uv run --locked --python "$py" pytest packages/viz/tests packages/crc/tests \
    --cov=parametric_insurance_design_viz --cov=parametric_insurance_design_crc \
    --cov-report=term-missing
  uv run --locked --python "$py" pytest parity/tests -v
}

job_core311() {
  local res=$1 venv=".venv-ci-core311-$1" version
  rm -rf "$venv"
  if ! uv venv --no-project --python "$py311" "$venv"; then
    echo "Python 3.11 unavailable here; falling back to 3.12."
    echo "Run scripts/ci_local.sh --setup, or set CI_LOCAL_PY311."
    uv venv --no-project --python 3.12 "$venv"
  fi
  version=$("$venv/bin/python" -c 'import platform; print(platform.python_version())')
  case $version in
    3.11.*) echo "python $version" >"$CI_LOCAL_NOTE" ;;
    *) echo "FALLBACK: python $version, not 3.11" >"$CI_LOCAL_NOTE" ;;
  esac
  uv pip install --python "$venv" --resolution "$res" ./packages/core
  local req="$logdir/test-requirements-$res.txt"
  uv export --locked --only-group test --no-hashes --no-annotate --no-header -o "$req"
  uv pip install --python "$venv" -r "$req"
  uv pip list --python "$venv"
  "$venv/bin/python" -m pytest packages/core/tests \
    --cov=parametric_insurance_design --cov-report=term-missing --cov-fail-under=85
}

check_licence() {
  local meta
  meta=$(unzip -p "$1"/"$2"-*.whl '*.dist-info/METADATA')
  echo "$meta" | grep -E '^(Name|Version|Requires-Python|License-Expression|License-File):'
  echo "$meta" | grep -qx "License-Expression: $3"
  echo "$meta" | grep -qx "License-File: LICENSE"
  echo
}

job_build() {
  local out="$logdir/dist"
  uv build --all-packages --out-dir "$out"
  uv build packages/climada --out-dir "$out"
  check_licence "$out" parametric_insurance_design BSD-3-Clause
  check_licence "$out" parametric_insurance_design_viz BSD-3-Clause
  check_licence "$out" parametric_insurance_design_crc AGPL-3.0-or-later
  check_licence "$out" parametric_insurance_design_climada GPL-3.0-or-later
}

job_climada() {
  cd packages/climada
  pixi install --locked
  pixi list --explicit
  pixi run --locked test
  pixi run --locked typecheck
  pixi run --locked test-core
}

for j in $selected; do
  case $j in
    lint) run_job lint job_lint ;;
    workspace-3.12) run_job workspace-3.12 job_workspace 3.12 ;;
    workspace-3.13) run_job workspace-3.13 job_workspace 3.13 ;;
    core-3.11-highest) run_job core-3.11-highest job_core311 highest ;;
    core-3.11-lowest-direct) run_job core-3.11-lowest-direct job_core311 lowest-direct ;;
    build) run_job build job_build ;;
    climada) run_job climada job_climada ;;
  esac
done

if [ $fail -eq 0 ]; then verdict="PASS"; else verdict="FAIL"; fi
echo "--- ci_local summary: $verdict for $head ($branch, $state), $((SECONDS - started)) s ---"
printf '%s' "$results"
if grep -qs FALLBACK "$logdir"/*.note; then
  echo "WARNING: the core-3.11 jobs ran on Python 3.12, not 3.11 (state this gap on the PR)."
fi
echo "logs: $logdir"
exit $fail
