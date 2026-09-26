#!/usr/bin/env bash
# Generation loop. A fact sheet goes in, the writer composes a paragraph under the
# prose contract, and a second session grades the paragraph against the contract,
# holding the fact sheet as the ORIGINAL.
#
# This is the compliance loop's counterpart for composition rather than editing.
# The rewrite loop can only measure restraint and repair on prose that already
# exists. A fact sheet has no sentences to preserve, so every fact the paragraph
# states either is on the sheet or is not, which makes invention and omission
# checkable the same way a rewrite's over-application is: by diffing against a
# source the judge can see.
#
# Same isolation as the rewrite loop and for the same reasons. The writer gets
# --setting-sources "" --plugin-dir <this plugin root>, which loads only the
# clanker-prose plugin (whose SessionStart hook points it at
# skills/prose/SKILL.md) while dropping this machine's user settings and hooks.
# The judge gets --bare, which loads no CLAUDE.md, no plugin, and no hook, so it
# holds only the catalog its own prompt carries.
#
# prompts/comply.txt needs no changes. It already grades an EDITED text against an
# ORIGINAL with no assumption that the original was prose: a violation is a banned
# span in the paragraph, and an over-application is a fact the sheet carried that
# the paragraph lost or flattened, which is the same "protected span the editor
# changed anyway" the rewrite loop already grades, read against a sheet instead of
# a paragraph.
#
# promptfoo exec provider. Receives the fact sheet as $1 and prints one artifact
# carrying the paragraph, the writer's notes, and the findings, in the same shape
# rewrite-then-comply.sh uses, so tools/comply-report.py needs no changes either.
set -euo pipefail

EVAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$(mktemp)"
MID="$(mktemp)"
trap 'rm -f "$SRC" "$MID"' EXIT
printf '%s' "$1" >"$SRC"

PLUGIN_ROOT="$(cd "$EVAL_ROOT/.." && pwd)"
args=(-p --strict-mcp-config --allowedTools Read Skill Write --output-format text
      --setting-sources "" --plugin-dir "$PLUGIN_ROOT"
      --mcp-config '{"mcpServers":{}}' --no-session-persistence)
[[ -n "${EVAL_MODEL:-}" ]] && args+=(--model "$EVAL_MODEL")

judge_args=(-p --output-format text --strict-mcp-config --bare
            --mcp-config '{"mcpServers":{}}' --no-session-persistence)
JM="${JUDGE_MODEL:-${EVAL_MODEL:-}}"
[[ -n "$JM" ]] && judge_args+=(--model "$JM")
judge_args+=(--effort "${JUDGE_EFFORT:-medium}")

strip_glyph() { perl -CSD -pe 'if ($. == 1) { s/^(?:[^\x00-\x7F]+\s*)+// }'; }

# Same catalog rule as the rewrite loop: rebuild on a stale mtime unless
# JUDGE_CATALOG pins a copy for an A/B, in which case that copy is authoritative
# and never rebuilt.
CONTRACT="${CONTRACT_FILE:-$EVAL_ROOT/../skills/prose/SKILL.md}"
CAT="${JUDGE_CATALOG:-$EVAL_ROOT/corpus/catalog.md}"
if [[ -z "${JUDGE_CATALOG:-}" ]] && { [[ ! -f "$CAT" ]] || [[ "$CONTRACT" -nt "$CAT" ]]; }; then
  TMP_CAT="$(mktemp)"
  python3 "$EVAL_ROOT/tools/extract-catalog.py" "$TMP_CAT"
  mv -f "$TMP_CAT" "$CAT"
fi
[[ -f "$CAT" ]] || { printf 'no catalog at %s\n' "$CAT" >&2; exit 1; }

NOTES_DIR="${REWRITE_NOTES_DIR:-$EVAL_ROOT/corpus/notes}"
mkdir -p "$NOTES_DIR"
HASH="$(shasum -a 256 "$SRC" | cut -c1-12)"
NOTES="$NOTES_DIR/$HASH.$$.txt"

write_prompt="$(python3 "$EVAL_ROOT/tools/render-template.py" \
  "$EVAL_ROOT/prompts/generate-notes.txt" --set "notes=$NOTES" input "$SRC")"
claude "${args[@]}" "$write_prompt" | strip_glyph >"$MID"

judge_prompt="$(python3 "$EVAL_ROOT/tools/render-template.py" \
  "$EVAL_ROOT/prompts/comply.txt" \
  catalog "$CAT" source "$SRC" rewrite "$MID")"

printf '<<<REWRITE>>>\n'
cat "$MID"
printf '<<<NOTES>>>\n'
cat "$NOTES" 2>/dev/null || printf 'NO NOTES FILE\n'
printf '<<<FINDINGS>>>\n'
claude "${judge_args[@]}" "$judge_prompt" | strip_glyph
