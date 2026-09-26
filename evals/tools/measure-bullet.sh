#!/usr/bin/env bash
# Measures one bullet before and after a catalog edit, with enough repeats that
# the difference means something.
#
# A single pass over ten cases cannot separate a rule improvement from model
# variance. Capture a baseline, edit the catalog, capture the result, and this
# prints the delta split by polarity. The rewrite arm and the preserve arm move
# in opposite directions under most edits, so a single overall number hides the
# trade the edit actually made.
#
# Usage
#   tools/measure-bullet.sh gnomic- before
#   ... edit skills/prose/SKILL.md ...
#   tools/measure-bullet.sh gnomic- after
#
# Environment
#   MEASURE_REPEATS  runs per case, default 5
#   MEASURE_JOBS     concurrency, default 12
set -euo pipefail

EVAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$EVAL_ROOT/corpus/measure"

if (( $# < 2 )); then
  printf 'usage: %s PATTERN before|after\n' "$(basename "$0")" >&2
  exit 2
fi

PATTERN="$1"
PHASE="$2"
REPEATS="${MEASURE_REPEATS:-5}"
JOBS="${MEASURE_JOBS:-12}"

if [[ "$PHASE" != "before" && "$PHASE" != "after" ]]; then
  printf 'phase must be before or after, got %s\n' "$PHASE" >&2
  exit 2
fi

mkdir -p "$OUT_DIR"
SLUG="$(printf '%s' "$PATTERN" | tr -c 'A-Za-z0-9' '-')"
RESULT="$OUT_DIR/$SLUG.$PHASE.json"

printf 'measuring %s, %s, %s repeats per case\n' "$PATTERN" "$PHASE" "$REPEATS" >&2
npx -y promptfoo@latest eval \
  --no-cache --no-table \
  -j "$JOBS" --repeat "$REPEATS" \
  --filter-pattern "$PATTERN" \
  -o "$RESULT" >/dev/null 2>&1

python3 "$EVAL_ROOT/tools/measure-report.py" \
  "$OUT_DIR/$SLUG.before.json" "$OUT_DIR/$SLUG.after.json"
