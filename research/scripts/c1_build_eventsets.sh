#!/usr/bin/env bash
# Build the F-12 EventSets that checkpoint C1 (MAR-29) uses as provisional
# sensitivities: the thesis portfolio with the cat-in-a-circle index (50 km)
# and/or vulnerability draws (10 per storm).
#
# Needs the CLIMADA pixi environment (packages/climada) and the IRIS catalogue
# (`pixi run iris`). By default the catalogue is read from the repository's
# git-ignored data/ folder; set IRIS_CATALOGUE to point elsewhere (e.g. the
# main checkout's data/ when running in a git worktree). EventSets go to
# results/c1/eventsets/ (git-ignored), or C1_EVENTSETS; they are never committed.
#
#   research/scripts/c1_build_eventsets.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CATALOGUE="${IRIS_CATALOGUE:-$ROOT/data/iris/transformed/IRIS_NA_10000Y_merged.txt}"
OUT="${C1_EVENTSETS:-$ROOT/results/c1/eventsets}"
mkdir -p "$OUT"

build() {  # <config, relative to packages/climada or absolute> <output name>
  if [ -d "$OUT/$2" ]; then
    echo "exists, kept: $OUT/$2"
    return
  fi
  (cd "$ROOT/packages/climada" && pixi run build-eventset --config "$1" \
    --catalogue "$CATALOGUE" --output "$OUT/$2")
}

build configs/thesis_cat_in_circle.yaml thesis-iris-cat-in-circle-50km
build configs/thesis_vulnerability.yaml thesis-iris-vulnerability
build configs/thesis_cat_in_circle_vulnerability.yaml thesis-iris-cat-in-circle-50km-vulnerability
build "$ROOT/research/configs/c1/eventsets/thesis_vulnerability_basins_null.yaml" \
  thesis-iris-vulnerability-basins-null
