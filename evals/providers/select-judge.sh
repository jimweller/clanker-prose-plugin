#!/usr/bin/env bash
# Pass one of the launder set. Asks whether a paragraph needs rewriting at all,
# which is a judgment about the writing rather than a guess at its provenance.
#
# The earlier selector ranked paragraphs by marker density and counted
# label-colon among the markers, so it picked scorecards written as paragraphs.
# This asks instead.
#
# promptfoo exec provider. Receives the paragraph as $1 and prints reasoning
# followed by a VERDICT line.
set -euo pipefail

EVAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PARA="$(mktemp)"
trap 'rm -f "$PARA"' EXIT
printf '%s' "$1" >"$PARA"

# --setting-sources "" gives a session that never loads ~/.claude/CLAUDE.md, this
# machine's user settings, or its hooks. Without it the judge can recite the
# catalog verbatim and grades the text against the contract rather than reading
# it, which turns every verdict into a compliance check on the rules that
# produced the text. No --bare: it disables plugin hooks unconditionally, and
# no --plugin-dir here, because this judge takes no side on style, only whether
# a paragraph needs rewriting at all.
args=(-p --output-format text --strict-mcp-config --setting-sources ""
      --mcp-config '{"mcpServers":{}}' --no-session-persistence)
[[ -n "${EVAL_MODEL:-}" ]] && args+=(--model "$EVAL_MODEL")

prompt="$(python3 "$EVAL_ROOT/tools/render-template.py" \
  "$EVAL_ROOT/prompts/select.txt" passage "$PARA")"

claude "${args[@]}" "$prompt" \
  | perl -CSD -pe 'if ($. == 1) { s/^(?:[^\x00-\x7F]+\s*)+// }'
