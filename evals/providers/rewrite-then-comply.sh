#!/usr/bin/env bash
# Compliance loop. A paragraph goes in, the contract rewrites it while recording
# which style-rules drove each decision, and a second session grades the edit
# against the contract text.
#
# This replaces the provenance question. The old judge asked whether a rewrite
# read human, which had no ground truth and could not tell a correct rewrite
# from an over-application, because both look like a lost human verdict. This
# one asks whether the edit complies, and names the style-rule behind every
# finding.
#
# The judge receives the contract through its prompt, which keeps the rule set
# versioned and visible in the run and keeps the persona, the chat register and
# the LSP rules out of a grader that has no use for them.
#
# --bare gives that directly for the judge. It skips hooks, LSP and plugin loading
# entirely, so a judge started anywhere holds nothing but its prompt. Probed from
# inside this repo it answers NO RULE when asked to quote PC-synthetic-negation.
# It costs nothing measurable, 25s against 21s on one case.
#
# The judge sees the original as well as the edit. Over-application is invisible from
# the output alone, since a deleted span leaves nothing behind to quote.
#
# promptfoo exec provider. Receives the passage as $1 and prints one artifact
# carrying the rewrite, the editor notes, and the findings.
set -euo pipefail

EVAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$(mktemp)"
MID="$(mktemp)"
trap 'rm -f "$SRC" "$MID"' EXIT
printf '%s' "$1" >"$SRC"

# The rewriter loads the clanker-prose plugin and nothing else. That is the thing
# under test.
#
# --setting-sources "" drops this machine's user settings, which is where the hooks
# live. On one 213-call run the claude-mem worker went unreachable for 65 consecutive
# hooks and some sessions returned the block banner in place of a rewrite, which the
# judge then graded as prose. That produced 10 PC-assistant-tool-leaks findings and 21
# runs with no notes file.
#
# --plugin-dir loads only the clanker-prose plugin, whose SessionStart hook points the
# rewriter at skills/prose/SKILL.md; the rewriter reads it directly (Read or Skill,
# either works, measured in Phase 0 probes) rather than relying on a ~/.claude/CLAUDE.md
# symlink resolving as a project source. --bare would also drop hooks but disables
# plugin hooks unconditionally, which removes the thing under test: measured directly,
# under --bare with --plugin-dir the session shows no plugin loaded at all.
#
# Write is allowed so the editor can put its notes in a file instead of in stdout, and
# Read/Skill are allowed so the SessionStart pointer can actually be followed.
# --allowedTools is variadic, so a flag has to follow it or it swallows the prompt
# argument and claude exits with "Input must be provided".
PLUGIN_ROOT="$(cd "$EVAL_ROOT/.." && pwd)"
args=(-p --strict-mcp-config --allowedTools Read Skill Write --output-format text
      --setting-sources "" --plugin-dir "$PLUGIN_ROOT"
      --mcp-config '{"mcpServers":{}}' --no-session-persistence)
[[ -n "${EVAL_MODEL:-}" ]] && args+=(--model "$EVAL_MODEL")

judge_args=(-p --output-format text --strict-mcp-config --bare
            --mcp-config '{"mcpServers":{}}' --no-session-persistence)
JM="${JUDGE_MODEL:-${EVAL_MODEL:-}}"
[[ -n "$JM" ]] && judge_args+=(--model "$JM")

# Medium effort, measured against the judge's own noise floor rather than assumed.
# Re-judging 48 stored rewrites with the same model and settings twice agreed on
# 39 percent of findings and 81 percent of clean-or-dirty verdicts. Opus at medium
# scored 30 and 79 against that floor, so it cannot be shown to differ. Sonnet
# scored 21 and 67, which is below the floor, and is not a substitute at any effort.
judge_args+=(--effort "${JUDGE_EFFORT:-medium}")

strip_glyph() { perl -CSD -pe 'if ($. == 1) { s/^(?:[^\x00-\x7F]+\s*)+// }'; }

# The contract is the judge's whole rule set, so a stale copy grades against rules
# that are no longer deployed. Rebuild whenever the source file moves.
#
# JUDGE_CATALOG pins it instead, which is how an A/B on a contract edit gets a clean
# read. Both sides otherwise load the same contract, so sharpening a rule teaches the
# judge what to look for at the same moment it tells the editor what to do, and the
# two effects cannot be separated. Measured: adding a modality clause to
# PC-add-nothing raised its finding count, and one finding cited the new clause by
# name while faulting the editor. That was a detector, not a repair.
#
# For an A/B, copy the pre-edit catalog aside and point JUDGE_CATALOG at it. Any
# movement is then the editor. The pinned copy grades against rules the editor no
# longer has, so use it only for the comparison and not for an absolute number.
CONTRACT="${CONTRACT_FILE:-$EVAL_ROOT/../skills/prose/SKILL.md}"
CAT="${JUDGE_CATALOG:-$EVAL_ROOT/corpus/catalog.md}"
if [[ -z "${JUDGE_CATALOG:-}" ]] && { [[ ! -f "$CAT" ]] || [[ "$CONTRACT" -nt "$CAT" ]]; }; then
  TMP_CAT="$(mktemp)"
  python3 "$EVAL_ROOT/tools/extract-catalog.py" "$TMP_CAT"
  mv -f "$TMP_CAT" "$CAT"
fi
[[ -f "$CAT" ]] || { printf 'no catalog at %s\n' "$CAT" >&2; exit 1; }

# The rewrite prompt invokes the prose skill and says nothing about how to write. A
# guard against a defect hides the defect. Telling the editor to invent no numbers
# duplicates PC-add-nothing and PC-computed-number and suppresses the exact failure the
# judge is about to grade, so the run scores the prompt instead of the contract.
#
# Notes go to a file rather than to stdout, so what this measures is what a real
# `/prose` run prints. The instruction sits after the rewrite instruction because an
# editor that enumerates before editing does not edit the way one that just edits does.
# Writing notes afterward reduces that effect without removing it, which is a known
# limit rather than a solved problem.
#
NOTES_DIR="${REWRITE_NOTES_DIR:-$EVAL_ROOT/corpus/notes}"
mkdir -p "$NOTES_DIR"
HASH="$(shasum -a 256 "$SRC" | cut -c1-12)"
NOTES="$NOTES_DIR/$HASH.$$.txt"

rewrite_prompt="$(python3 "$EVAL_ROOT/tools/render-template.py" \
  "$EVAL_ROOT/prompts/rewrite-notes.txt" --set "notes=$NOTES" input "$SRC")"
claude "${args[@]}" "$rewrite_prompt" | strip_glyph >"$MID"

judge_prompt="$(python3 "$EVAL_ROOT/tools/render-template.py" \
  "$EVAL_ROOT/prompts/comply.txt" \
  catalog "$CAT" source "$SRC" rewrite "$MID")"

printf '<<<REWRITE>>>\n'
cat "$MID"
printf '<<<NOTES>>>\n'
cat "$NOTES" 2>/dev/null || printf 'NO NOTES FILE\n'
printf '<<<FINDINGS>>>\n'
claude "${judge_args[@]}" "$judge_prompt" | strip_glyph
