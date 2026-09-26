#!/usr/bin/env bash
# Re-judges rewrites that a previous run already produced, using a different model.
#
# The point is to size the judge independently of the rewriter. The rewriter is the
# thing under test and stays on the deployed model. The judge is instrumentation, so
# it only has to read the same as the one it replaces.
#
# Re-running the whole pipeline would prove nothing. The rewriter is non-deterministic,
# so two pipeline runs give the two judges different text to score and any difference
# in findings could come from either half. This reads the stored rewrites instead, so
# both judges see identical input and the only variable is the model.
#
# Usage
#   tools/calibrate-judge.sh RESULT_JSON MODEL [PARALLEL] [EFFORT]
#
# EFFORT maps to claude's --effort flag and is left unset by default, which takes
# the session default. Results land under a directory naming both, so runs at
# different efforts do not overwrite each other.
#
# Writes one file per case to corpus/calibrate/<model>[-<effort>]/ and prints nothing
# but progress. tools/calibrate-report.py does the comparison.
set -euo pipefail

EVAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULT="${1:?usage: calibrate-judge.sh RESULT_JSON MODEL [PARALLEL] [EFFORT]}"
MODEL="${2:?usage: calibrate-judge.sh RESULT_JSON MODEL [PARALLEL] [EFFORT]}"
PAR="${3:-48}"
EFFORT="${4:-}"

OUT="$EVAL_ROOT/corpus/calibrate/$MODEL${EFFORT:+-$EFFORT}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$OUT"

# Pull source and rewrite out of the stored run, one pair per case.
python3 - "$RESULT" "$WORK" <<'PY'
import json, pathlib, re, sys
result, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
rows = (json.loads(result.read_text()).get("results") or {}).get("results") or []
SEC = re.compile(r"<<<(NOTES|REWRITE|FINDINGS)>>>")
def split(t):
    p, last, pos = {}, None, 0
    for m in SEC.finditer(t):
        if last: p[last] = t[pos:m.start()].strip()
        last, pos = m.group(1), m.end()
    if last: p[last] = t[pos:].strip()
    return p
n = 0
for i, r in enumerate(rows):
    out = (r.get("response") or {}).get("output") or ""
    if "<<<REWRITE>>>" not in out: continue
    v = (r.get("testCase") or {}).get("vars") or {}
    parts = split(out)
    case = (v.get("__description")
            or (r.get("testCase") or {}).get("description") or f"case-{i:03d}")
    d = work / case
    d.mkdir(parents=True, exist_ok=True)
    (d / "source.txt").write_text(v.get("passage", ""))
    (d / "rewrite.txt").write_text(parts.get("REWRITE", ""))
    # The stored findings are the incumbent judge's verdict on this same rewrite.
    (d / "incumbent.txt").write_text(parts.get("FINDINGS", ""))
    n += 1
print(f"{n} cases extracted", file=sys.stderr)
PY

CAT="$EVAL_ROOT/corpus/catalog.md"
[[ -f "$CAT" ]] || python3 "$EVAL_ROOT/tools/extract-catalog.py" "$CAT"

judge_one() {
    local d="$1" model="$2" root="$3" out="$4" effort="$5"
    local case; case="$(basename "$d")"
    local prompt; prompt="$(python3 "$root/tools/render-template.py" \
        "$root/prompts/comply.txt" \
        catalog "$root/corpus/catalog.md" \
        source "$d/source.txt" rewrite "$d/rewrite.txt")"
    local args=(-p --output-format text --strict-mcp-config
                --setting-sources project --mcp-config '{"mcpServers":{}}'
                --no-session-persistence --model "$model")
    [[ -n "$effort" ]] && args+=(--effort "$effort")
    local jail; jail="$(mktemp -d)"
    # Same isolation the live provider uses. --setting-sources project alone does not
    # isolate a session whose cwd sits inside the dotfiles repo, so it runs elsewhere.
    (cd "$jail" && claude "${args[@]}" "$prompt") \
        | perl -CSD -pe 'if ($. == 1) { s/^(?:[^\x00-\x7F]+\s*)+// }' >"$out/$case.txt"
    rm -rf "$jail"
    cp "$d/incumbent.txt" "$out/$case.incumbent.txt"
    printf '.' >&2
}
export -f judge_one

find "$WORK" -mindepth 1 -maxdepth 1 -type d -print0 \
  | xargs -0 -P "$PAR" -I '{}' bash -c 'judge_one "$@"' _ '{}' "$MODEL" "$EVAL_ROOT" "$OUT" "$EFFORT"
printf '\n%s judged with %s, written to %s\n' \
  "$(ls -1 "$OUT"/*.txt 2>/dev/null | grep -vc incumbent || echo 0)" "$MODEL" "$OUT"
