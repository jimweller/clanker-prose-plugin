#!/usr/bin/env bash
# promptfoo exec provider. Receives the rendered prompt as $1 and prints the
# reply on stdout.
#
# MCP servers and session persistence are off so a run measures the
# clanker-prose plugin rather than the surrounding tooling. --setting-sources ""
# drops this machine's user settings and hooks; --plugin-dir loads only this
# plugin, whose SessionStart hook points the session at skills/prose/SKILL.md.
# Not --bare: it disables plugin hooks unconditionally, which would stop the
# contract pointer from ever firing. Set EVAL_MODEL to pin a model, otherwise
# the session default applies.
set -euo pipefail

EVAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_ROOT="$(cd "$EVAL_ROOT/.." && pwd)"

args=(
  -p
  --output-format text
  --strict-mcp-config
  --setting-sources ""
  --plugin-dir "$PLUGIN_ROOT"
  --allowedTools "Read,Skill"
  --mcp-config '{"mcpServers":{}}'
  --no-session-persistence
)

if [[ -n "${EVAL_MODEL:-}" ]]; then
  args+=(--model "$EVAL_MODEL")
fi

# skills/prose/SKILL.md still carries a STARTER_CHARACTER line inherited from the
# original clanker-skills prose skill. That marker belongs to the chat register
# rather than the artifact under test (and this isolated session loads no
# CLAUDE.md to give it meaning anyway), so the leading run of non-ASCII
# characters comes off line 1 before grading, defensively.
claude "${args[@]}" "$1" | perl -CSD -pe 'if ($. == 1) { s/^(?:[^\x00-\x7F]+\s*)+// }'
