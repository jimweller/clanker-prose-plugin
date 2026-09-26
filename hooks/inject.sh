#!/bin/bash
set -euo pipefail
event="${1:?event name required}"
root="${CLAUDE_PLUGIN_ROOT:?CLAUDE_PLUGIN_ROOT not set}"
skill_file="${root}/skills/prose/SKILL.md"
[ -f "$skill_file" ] || { echo "clanker-prose inject.sh: missing $skill_file" >&2; exit 1; }
python3 -c "
import json, sys, os
event = sys.argv[1]
skill_path = sys.argv[2]
text = (
    'Before writing any prose for a human reader (commits, PR bodies, docs, Slack, email, '
    'code comments, or chat replies), read the full contract at ' + skill_path +
    ' (via the Skill tool or a direct Read, either works) and follow it. Read it once now, '
    'before doing anything else.'
)
print(json.dumps({'hookSpecificOutput': {'hookEventName': event, 'additionalContext': text}}))
" "$event" "$skill_file"
