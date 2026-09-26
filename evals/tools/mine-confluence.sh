#!/usr/bin/env bash
# Pulls Confluence page bodies and keeps the ones dense enough in em-dashes to
# be worth scanning for catalog violations.
#
# Requires the mcg-atlassian confluence plugin cache. Writes to corpus/raw/,
# which is gitignored, because both repos that carry this suite are public.
#
# Resumable. A page already cached is skipped, so a run can be interrupted and
# restarted without refetching.
#
# Environment
#   MINE_SINCE     ISO date, default one year back
#   MINE_LIMIT     how many page ids to consider, default 200
#   MINE_PARALLEL  concurrent page fetches, default 6
#   MINE_MIN_DASH  em-dash count that marks a page, default 3
set -euo pipefail

EVAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORPUS_DIR="$EVAL_ROOT/corpus"
RAW_DIR="$CORPUS_DIR/raw"

C_CLI="$HOME/.claude/plugins/cache/sead-claude-marketplace/mcg-atlassian/0.9.0/skills/confluence/c-cli"
C=(uv run --project "$C_CLI" c)

MINE_SINCE="${MINE_SINCE:-$(date -v-1y +%Y-%m-%d 2>/dev/null || date -d '1 year ago' +%Y-%m-%d)}"
MINE_LIMIT="${MINE_LIMIT:-200}"
MINE_PARALLEL="${MINE_PARALLEL:-6}"
MINE_MIN_DASH="${MINE_MIN_DASH:-3}"

mkdir -p "$RAW_DIR"

# One query per month rather than one for the whole window. A single
# `created >= X ORDER BY created DESC` with a limit returns the newest N, which
# gave a corpus spanning 9 days when the window was a year. Monthly buckets
# spread the sample evenly across it.
MINE_MONTHS="${MINE_MONTHS:-12}"
PER_MONTH=$(( (MINE_LIMIT + MINE_MONTHS - 1) / MINE_MONTHS ))
printf 'searching %s months back to %s, %s pages per month\n' \
  "$MINE_MONTHS" "$MINE_SINCE" "$PER_MONTH" >&2

BUCKETS="$(mktemp)"
PARTS="$(mktemp -d)"
trap 'rm -rf "$BUCKETS" "$PARTS"' EXIT
python3 "$EVAL_ROOT/tools/month-buckets.py" "$MINE_SINCE" "$MINE_MONTHS" >"$BUCKETS"

while IFS=' ' read -r from to; do
  [[ -n "$from" ]] || continue
  "${C[@]}" --output json page search \
    "created >= \"$from\" and created < \"$to\" ORDER BY created DESC" \
    --max-results "$PER_MONTH" >"$PARTS/$from.json" 2>/dev/null
  printf '  %s to %s  %s pages\n' "$from" "$to" \
    "$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))))" "$PARTS/$from.json" 2>/dev/null || echo 0)" >&2
done <"$BUCKETS"

python3 -c "
import json, pathlib, sys
seen, out = set(), []
for p in sorted(pathlib.Path(sys.argv[1]).glob('*.json')):
    try: rows = json.load(open(p))
    except Exception: continue
    for r in rows:
        if r['id'] in seen: continue
        seen.add(r['id']); out.append(r)
json.dump(out, open(sys.argv[2], 'w'), indent=2)
print(f'merged {len(out)} unique pages across the window', file=sys.stderr)
" "$PARTS" "$CORPUS_DIR/index.json"

python3 -c "
import json, sys
with open('$CORPUS_DIR/index.json') as fh:
    for page in json.load(fh):
        print(page['id'])
" >"$CORPUS_DIR/ids.txt"

printf 'fetching bodies with %s workers\n' "$MINE_PARALLEL" >&2
export C_CLI RAW_DIR
# shellcheck disable=SC2016
xargs -P "$MINE_PARALLEL" -I '{}' bash -c '
  set -euo pipefail
  out="$RAW_DIR/{}.json"
  [[ -s "$out" ]] && exit 0
  uv run --project "$C_CLI" c --output json page get "{}" >"$out"
' <"$CORPUS_DIR/ids.txt"

printf 'counting em-dash markers\n' >&2
python3 - "$RAW_DIR" "$CORPUS_DIR/index.json" "$MINE_MIN_DASH" <<'PY' >"$CORPUS_DIR/manifest.json"
import json, pathlib, re, sys

raw_dir, index_path, min_dash = pathlib.Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
titles = {p["id"]: p["title"] for p in json.load(open(index_path))}

# Storage format returns an em-dash as an entity, so a literal-character scan
# finds nothing. The spaced double hyphen is the catalog's sneaky em-dash.
MARKERS = re.compile(r"&mdash;|&#8212;|—|(?<![\w-])--(?![\w-])")

rows, scanned = [], 0
for path in sorted(raw_dir.glob("*.json")):
    try:
        page = json.loads(path.read_text())
    except json.JSONDecodeError:
        continue
    body = page.get("body", {}).get("storage", {}).get("value", "")
    if not body:
        continue
    scanned += 1
    hits = len(MARKERS.findall(body))
    if hits >= min_dash:
        rows.append({
            "id": page.get("id", path.stem),
            "title": titles.get(page.get("id"), page.get("title", "")),
            "dashes": hits,
            "bytes": len(body),
        })

rows.sort(key=lambda r: r["dashes"], reverse=True)
json.dump({"scanned": scanned, "flagged": len(rows), "min_dash": min_dash, "pages": rows},
          sys.stdout, indent=2)
PY

python3 -c "
import json
m = json.load(open('$CORPUS_DIR/manifest.json'))
print()
print('scanned %d pages, %d flagged at %d or more em-dashes (%.0f%%)' % (
    m['scanned'], m['flagged'], m['min_dash'],
    100 * m['flagged'] / m['scanned'] if m['scanned'] else 0))
for row in m['pages'][:15]:
    print('  %4d  %s' % (row['dashes'], row['title'][:70]))
"
