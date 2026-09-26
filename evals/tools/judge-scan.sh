#!/usr/bin/env bash
# Runs a judgment pass over corpus chunks, one bullet group per call.
#
# The catalog reaches the judge through the clanker-prose plugin's SessionStart
# hook pointer (Read or Skill on skills/prose/SKILL.md), so no rules text
# travels in the prompt and the scan exercises the same contract the eval
# grades.
#
# Resumable. A chunk-and-group pair with a result file is skipped.
#
# Every python step is a file under tools/ rather than an inline heredoc. The
# inline version nested a multi-line string inside a command substitution inside
# a single-quoted xargs body and failed with no output at all.
#
# Environment
#   SCAN_SOURCE    corpus subdirectory of chunks, default raw
#   SCAN_GROUPS    space-separated group names, default all in bullet-groups.json
#   SCAN_LIMIT     how many chunks to process, 0 means all
#   SCAN_PARALLEL  concurrent judge calls, default 6
#   SCAN_MODEL     model override passed to claude -p
set -euo pipefail

EVAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_ROOT="$(cd "$EVAL_ROOT/.." && pwd)"
TOOLS="$EVAL_ROOT/tools"
CORPUS="$EVAL_ROOT/corpus"

SCAN_SOURCE="${SCAN_SOURCE:-raw}"
SCAN_LIMIT="${SCAN_LIMIT:-0}"
SCAN_PARALLEL="${SCAN_PARALLEL:-6}"
SCAN_MODEL="${SCAN_MODEL:-}"

CHUNK_DIR="$CORPUS/chunks/$SCAN_SOURCE"
OUT_DIR="$CORPUS/candidates/$SCAN_SOURCE"
GROUPS_JSON="$TOOLS/bullet-groups.json"
TEMPLATE="$TOOLS/scan-prompt.txt"

if [[ ! -d "$CHUNK_DIR" ]]; then
  printf 'no chunks at %s, run tools/chunk-corpus.py first\n' "$CHUNK_DIR" >&2
  exit 1
fi
mkdir -p "$OUT_DIR"

# The array is BULLET_GROUPS, never GROUPS. Bash owns GROUPS as a special
# variable holding the current user's Unix group ids and keeps repopulating it,
# so every assignment to it silently produced a list of gids instead of bullet
# group names, and mapfile into it took the script down under set -e with no
# message at all.
GROUP_FILE="$(mktemp)"
CHUNK_FILE="$(mktemp)"
JOBS="$(mktemp)"
trap 'rm -f "$GROUP_FILE" "$CHUNK_FILE" "$JOBS"' EXIT

if [[ -n "${SCAN_GROUPS:-}" ]]; then
  tr ' ' '\n' <<<"$SCAN_GROUPS" >"$GROUP_FILE"
else
  python3 "$TOOLS/scan-groups.py" "$GROUPS_JSON" >"$GROUP_FILE"
fi

BULLET_GROUPS=()
while IFS= read -r g || [[ -n "$g" ]]; do
  [[ -n "$g" ]] && BULLET_GROUPS+=("$g")
done <"$GROUP_FILE"

if (( ${#BULLET_GROUPS[@]} == 0 )); then
  printf 'no bullet groups resolved from %s\n' "$GROUPS_JSON" >&2
  exit 1
fi

find "$CHUNK_DIR" -name '*.txt' | sort >"$CHUNK_FILE"
CHUNKS=()
while IFS= read -r chunk || [[ -n "$chunk" ]]; do
  [[ -n "$chunk" ]] && CHUNKS+=("$chunk")
done <"$CHUNK_FILE"

if (( SCAN_LIMIT > 0 )) && (( ${#CHUNKS[@]} > SCAN_LIMIT )); then
  CHUNKS=("${CHUNKS[@]:0:SCAN_LIMIT}")
fi

printf 'scanning %d chunks across %d groups, %d workers\n' \
  "${#CHUNKS[@]}" "${#BULLET_GROUPS[@]}" "$SCAN_PARALLEL" >&2

for chunk in "${CHUNKS[@]}"; do
  for group in "${BULLET_GROUPS[@]}"; do
    # Space separated, not tab. xargs -I normalises a tab to a space, so a tab
    # delimiter arrives as something the callee cannot split on. Chunk paths
    # carry no spaces and group names carry none either, so a last-space split
    # is unambiguous.
    printf '%s %s\n' "$chunk" "$group" >>"$JOBS"
  done
done

export TOOLS OUT_DIR GROUPS_JSON TEMPLATE SCAN_MODEL PLUGIN_ROOT

run_one() {
  local chunk group base out prompt
  # Parameter expansion rather than `read`, for the same set -e reason as above.
  chunk="${1% *}"
  group="${1##* }"
  base="$(basename "$chunk" .txt)"
  out="$OUT_DIR/$base.$group.json"
  [[ -s "$out" ]] && return 0

  prompt="$(python3 "$TOOLS/scan-render.py" "$GROUPS_JSON" "$group" "$chunk" "$TEMPLATE")"

  local args=(-p --output-format text --strict-mcp-config
              --setting-sources "" --plugin-dir "$PLUGIN_ROOT"
              --allowedTools "Read,Skill"
              --mcp-config '{"mcpServers":{}}' --no-session-persistence)
  [[ -n "$SCAN_MODEL" ]] && args+=(--model "$SCAN_MODEL")

  claude "${args[@]}" "$prompt" \
    | perl -CSD -pe 'if ($. == 1) { s/^(?:[^\x00-\x7F]+\s*)+// }' \
    >"$out.raw" || { printf 'call failed for %s %s\n' "$base" "$group" >&2; return 0; }

  if python3 "$TOOLS/scan-extract.py" "$out.raw" "$out" 2>/dev/null; then
    rm -f "$out.raw"
  else
    mv "$out.raw" "$out.badjson"
  fi
}
export -f run_one

xargs -P "$SCAN_PARALLEL" -I '{}' bash -c 'run_one "$@"' _ '{}' <"$JOBS"

python3 "$TOOLS/aggregate-candidates.py" --source "$SCAN_SOURCE"
