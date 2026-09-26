# Prose eval suite

Two instruments measuring the same contract at different scales.

The rewrite suite grades one rule at a time on a sentence or two, with string
assertions checking that a marker went away and a fact survived. The compliance
loop takes a whole Confluence paragraph, hands it to the prose skill, and has a
separate session grade the edit against the contract.

The contract is `skills/prose/SKILL.md` in this repo, which is the source of truth
and the only copy to edit. A `<prose-contract>` tag wraps the three sections that
make up the written-artifact contract, and every rule inside opens with a `PC-` id.
The plugin's `SessionStart`/`SubagentStart` hook (`hooks/inject.sh`) points a
loaded session at this file and the session reads it directly, so editing it
changes what both suites score the next time a hook fires.

## Running it

```bash
cd evals
npx promptfoo@0.123.1 eval --no-cache                                   # rewrite suite, 595 cases
npx promptfoo@0.123.1 eval -c promptfooconfig.comply.yaml --no-cache    # compliance loop, 71 paragraphs
npx promptfoo@0.123.1 eval -c promptfooconfig.generate.yaml --no-cache  # generation loop, 15 fact sheets
tools/comply-report.py /tmp/out.json                                    # triage either loop's run
node --test tests/ && python3 -m unittest discover -s tests -p 'test_*.py'
```

No install step. The writers and judges authenticate through the parent shell's
Foundry or Anthropic key and read routing from `~/.claude/settings.json`, so no
API key goes in a config. `corpus/comply.csv` is gitignored because it holds mined
Confluence text. It was rebuilt on 2026-09-26 from the test vars that promptfoo
stored in `~/.promptfoo/promptfoo.db` for eval `eval-FBV-2026-09-19T12:05:05`.

## The promptfoo judge

The compliance and generation loops grade inside promptfoo.
`providers/writer.py` runs one `claude -p` writer per case with
`--setting-sources ""` and `--plugin-dir` on this plugin, from a fresh temp
directory. `graders/judge.js` runs three `claude -p --bare` judge passes against
`prompts/comply-json.txt` with a JSON schema whose rule enum is the contract's
`PC-` ids. A row is clean when a majority of passes report no finding. Every row
carries namedScores for the derived metrics, and one componentResults entry per
`(kind, rule)` finding with each pass's span.

| Knob                          | Default                                                                | Effect                                                                                           |
| ----------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `EVAL_MODEL`                  | `opus`                                                                 | Writer model alias                                                                               |
| `EVAL_EFFORT`                 | the alias's `modelSettings` `effortLevel` in `~/.claude/settings.json` | Writer effort, so a run matches a real session                                                   |
| `JUDGE_MODEL`, `JUDGE_EFFORT` | `opus`, `medium`                                                       | Judge model alias and effort                                                                     |
| `JUDGE_PASSES`                | 3                                                                      | Judge passes per row                                                                             |
| `JUDGE_MODE`                  | `whole`                                                                | `groups` splits each pass into the four `tools/bullet-groups.json` groups plus a 54-id remainder |
| `JUDGE_CATALOG`               | unset                                                                  | Pins the judge to a catalog copy for an A/B                                                      |
| `JUDGE_MAX_PROCS`             | 96                                                                     | Concurrent judge processes per promptfoo run                                                     |
| `REWRITE_NOTES_DIR`           | `corpus/notes`                                                         | Where the editor's notes land                                                                    |

Env beats config, which beats the default. `tools/comply-report.py` recomputes
every rate and exits 1 on a mismatch with promptfoo's derived metrics, a cached
row, a judge error, or a writer error. Findings are per row, by majority unless
`--findings union` is passed.

The editor writes its notes inside its own temp directory, and the provider copies
them to `REWRITE_NOTES_DIR`. Claude Code refuses a write inside a `--plugin-dir`
directory as a sensitive file, and `corpus/notes` sits inside the plugin.

`promptfooconfig.comply.rejudge.yaml` grades stored rewrites again without running
the writer. `tools/rejudge-tests.py` builds its tests from a prior `-o` JSON.
`tools/judge-agreement.py` compares the judge's passes within one run, or two
rejudges of the same text.

The generation writer uses `prompts/generate.txt`, which asks for no notes. The
`opus` 5.5 safeguard refused a version of it that asked for notes with
`reasoning_extraction` on 4 of 4 calls.

## What the compliance loop measures

Each case runs two sessions. The rewriter invokes the prose skill on a paragraph
and writes its notes to a file. A second session receives the original, the
rewrite, and the contract, and reports findings of two opposite kinds.

A **violation** is a span in the rewrite that a rule bans and no exemption covers.
An **over-application** is a span in the original that an exemption protected,
which the editor changed anyway. A single pass-or-fail score cannot tell those
apart, and they call for opposite repairs: a violation means a rule is too weak, an
over-application means its exemption is.

`tools/comply-report.py` buckets the findings by diffing the editor's notes against
the judge's findings.

| Bucket                    | Means                                                                     |
| ------------------------- | ------------------------------------------------------------------------- |
| `self-inflicted`          | The violating span is absent from the original, so the rewrite created it |
| `fired-then-over-applied` | The editor recorded applying the rule and an exemption covered the span   |
| `held-then-violation`     | The editor recorded an exemption and the judge rejected it                |
| `over-applied-untraced`   | Cut a protected span without recording the rule at all                    |
| `unseen-violation`        | The judge cites a rule the notes never mention                            |

## What the generation loop measures

The compliance loop only ever grades a rewrite of prose that already exists, so it
cannot check for an invented or dropped fact, and it cannot catch a rule that only
bites during first-draft composition rather than editing. `promptfooconfig.generate.yaml`
runs a second loop for that: a fact sheet in `cases/generate.csv` goes in, a writer
composes one paragraph under the prose contract, and the same judge prompt grades
the paragraph with the sheet standing in as the ORIGINAL. `prompts/comply-json.txt` needs
no change, since it grades an EDITED text against an ORIGINAL with no
assumption that the original was prose.

Each sheet is discrete facts, no sentences, so every fact the paragraph states either
is on the sheet or is not. Each sheet carries five elements, each tempting a specific
rule group: two facts with a causal link (em-dashes, semicolons, colons, marker
substitution), a tradeoff or rejected alternative (phantom-foil, opposing phrases),
four or more parallel items (parallel triads, coordination), a hedged or bounded claim
(evidential-status, hedging adjuncts, flattened calibration), and a scoping quantifier,
modal, or tense that matters (`PC-add-nothing`). 15 sheets across three topic shapes:
an incident with a root cause and a costed mitigation, a capacity decision with a
number, a deadline, and a rejected option, and a migration with a measured benefit and
an unmeasured risk.

`providers/writer.py` composes the paragraph with `task: generate` under the same
isolation as the rewriter. `graders/judge.js` grades it the same way as a rewrite, so
`tools/comply-report.py` reads runs from both loops. The `self-inflicted` bucket
misleads on this loop. It keys on whether a violating span appears verbatim in the
source. A fact sheet's fragments never match a composed sentence's wording, so nearly
every violation reads as `self-inflicted` whether or not the paragraph invented
anything. Read the clean rate on this loop and ignore its bucket split.

A sheet must not carry a construction the contract bans, because the writer carries
it into the paragraph and the loop then tests the sheet instead of the writer. A
hedged claim names a real subject ("No test has confirmed whether X"), never a
clausal subject ("Whether X or Y has not been tested") or a dummy "it". A decision
takes the decided thing as its subject ("Two new read replicas were approved"), never
a gerund ("Adding two read replicas was approved"). Sheets carry
no label-colon prefix such as `Root cause:`, no colon introducing a list, and no
semicolon. Each sheet is one line of period-separated fragments with no bullet
markers, so the judge has no list to call collapsed under `PC-round-trip-damage`.

## Where the numbers stand

Every number in this section was measured through the plugin on 2026-09-26. The
compliance and generation writers ran at the effort a real session uses, `opus` at
xhigh for a main session and `sonnet` at high for a subagent. Every writer loaded the
contract.

The compliance loop ran once per writer at `--repeat 3`. The class columns count rows
clean by majority.

| Writer        | Judged     | Clean by majority | Clean per pass | `good`   | `mixed`  | `slop`   |
| ------------- | ---------- | ----------------- | -------------- | -------- | -------- | -------- |
| `opus` xhigh  | 212 of 213 | 172 of 212        | 509 of 636     | 66 of 80 | 73 of 84 | 33 of 48 |
| `sonnet` high | 213 of 213 | 99 of 213         | 287 of 639     | 45 of 81 | 43 of 84 | 11 of 48 |

The generation loop scored 31 of 45 rows clean with the `opus` writer and 16 of 45
with `sonnet`.

`sonnet` changed a span an exemption protected on 24 of 213 compliance rows, and
`opus` on 1 of 212. `PC-add-nothing` leads the `sonnet` findings, 34 of 143 in the
compliance loop and 14 of 40 in the generation loop. `PC-parallel-triads` leads the
`opus` compliance findings, 15 of 43.

The `opus` 5.5 safeguard refused 8 writer attempts across 6 compliance rows with
`reasoning_extraction`. The retry recovered 5 of those rows. The sixth was refused on
all 3 attempts and is the one unjudged row.

The rewrite suite passed 555 of 595 cases on one run and 553 of 595 on a second. Its
provider, `providers/deployed.sh`, pins no effort, so both runs used the CLI default.

## What this instrument can and cannot measure

**Only the clean rate is reliable.** Two passes of the judge on the same rewrite
agreed on clean or dirty for 562 of 636 pass pairs on the `opus` compliance run and
523 of 639 on the `sonnet` run. They agreed on 89 of 191 findings and 319 of 643.
Finding agreement sits well below clean agreement, so per-rule counts carry more
noise than the clean rate.

**Both sides read the same contract**, so sharpening a rule teaches the judge what
to look for at the same moment it instructs the editor. For an A/B, copy the
pre-edit catalog aside and point `JUDGE_CATALOG` at it, which pins the grader so any
movement is the editor.

```bash
cp corpus/catalog.md /tmp/catalog-pinned.md
# edit the contract
JUDGE_CATALOG=/tmp/catalog-pinned.md npx promptfoo@latest eval \
  -c promptfooconfig.comply.yaml --repeat 3 -j 96 -o /tmp/after.json
```

**Run an A/B twice before believing it.** One run is a direction, two are a result.

### Measuring the source baseline

Judging the sources with the rewrite set equal to the source gives the floor.
`promptfooconfig.comply.rejudge.yaml` does this when its tests carry no
`providerOutput`, because its `echo` provider then returns the rendered passage.
Write `corpus/comply.csv` into the rejudge tests file and run the config.

```bash
python3 - <<'PY'
import csv, json, pathlib
tests = [{"description": r["__description"], "vars": {k: v for k, v in r.items() if not k.startswith("__")}}
         for r in csv.DictReader(open("corpus/comply.csv"))]
out = pathlib.Path("corpus/rejudge/comply.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(tests, indent=1, ensure_ascii=False) + "\n")
PY
npx promptfoo@0.123.1 eval -c promptfooconfig.comply.rejudge.yaml --no-cache -o /tmp/source.json
tools/comply-report.py /tmp/source.json
```

This overwrites the stored rewrites in `corpus/rejudge/comply.json`.
`tools/rejudge-tests.py` rebuilds them from a run's `-o` JSON.

## Isolation

Eval sessions inherit this machine's configuration unless told otherwise, and both
kinds of leak have already corrupted a run.

**Hooks.** The claude-mem worker once went unreachable during a run. Some sessions
returned its block banner in place of a rewrite, which the judge graded as prose.
`providers/writer.py` now runs the rewriter with
`--setting-sources "" --plugin-dir <this plugin root>`, which drops every
machine-level setting, including the hooks that caused the failure, and loads only
this plugin. The contract and the skill are the same file, `skills/prose/SKILL.md`.
The plugin's `SessionStart` hook points the rewriter at it and the rewriter reads it
directly.

**The contract reaching the judge twice.** The judge is supposed to hold only the
catalog its prompt carries. `graders/judge.js` runs it with `--bare`, which loads no CLAUDE.md, no
plugin, and no hook, so nothing but the prompt's own catalog text reaches it.
`--bare` is wrong for the rewriter for a different reason now: it disables plugin
hooks unconditionally (measured directly, not inferred), which would stop the
rewriter's own contract pointer from ever firing.

## The corpus

`corpus/comply.csv` holds 71 paragraphs selected by reading all 262 candidates
rather than by a filter. An `expect` column records the judgment a reader should
reach.

| Class   | n   | Tests                                             |
| ------- | --- | ------------------------------------------------- |
| `good`  | 27  | Restraint. A rewrite should change almost nothing |
| `mixed` | 28  | Ordinary technical prose                          |
| `slop`  | 16  | Repair. Generic openings, triads, hype            |

The `good` set comes from the SEAD platform pages, which are the prose the contract
was written from. Two of the selected paragraphs appear in the contract as exemption
examples. That gives the suite a ceiling, since damage to those is over-application
with no ambiguity about the source.

The previous selection took the 60 longest paragraphs the judge wanted rewritten on
every pass, which loaded the set entirely with defective text and made
over-application nearly unmeasurable. It also keyed on passage text and discarded
the page id the pool already carried, so no case traced back to a page. Selection
now round-robins across spaces and authors and writes `page_id`, `space_id`,
`author_id`, `created` and `expect`.

Meeting minutes are excluded. They are AI-transcribed attributed speech rather than
authored prose. A prose contract has no business being measured on them. Also
excluded: Jira ADF JSON dumps, UUID action-item lists, testimonial quotes, and PRD
boilerplate that appeared verbatim on three separate pages.

Everything under `corpus/` is gitignored and stays that way. Both repos holding this
suite are public, so mined page bodies never get committed. A case reaching
`cases/*.csv` is written fresh over invented facts.

## Rule ids

Every rule opens with a `PC-` id, 76 in total, 55 in `Banned Patterns` and 21 in
`Ghostwriting`. The five moves in `How to Write` keep their `[move N]` tags, which
already cross-reference from every banned-pattern rule.

Free-text rule names did not survive two sessions. A judge scored one rule under two
different names, which split its count. An id is either in the contract or it is not,
so `comply-report.py` reports any finding citing an id the contract does not define.

`tools/check-anchors.py` fails on an unknown id, a rule with no id or two, a
duplicate id, a `[move N]` pointing at nothing, and a `corpus/catalog.md` whose
content differs from the contract. That last check exists because the provider
rebuilds the catalog on an `mtime` comparison, which a `git checkout` defeats.

Watch for terms the callers use that the contract never defines. `style-rule`
appeared once in the judge prompt carrying the definition of a violation, and zero
times in the contract, so the judge had to infer it. Same defect as
`house prose contract`, which the contract also never answered to.

## Measuring a rule change

One pass per case cannot tell a rule improvement from model variance.

```bash
tools/measure-bullet.sh gnomic- before
# edit skills/prose/SKILL.md
tools/measure-bullet.sh gnomic- after
```

That runs five repeats per case and prints the delta split by polarity. Read the two
arms rather than the overall number, because most contract edits move them in
opposite directions. Telling an editor to cut harder raises the rewrite arm and
lowers the preserve arm.

### The triad and passive rewording, 2026-09-26

The `PC-parallel-triads` exemption was narrowed to ordered sequences, and the
`PC-agentless-passive` exemption to a passive whose sentence names no actor. The judge
was pinned to the pre-edit catalog. The measurement reran the 19 compliance paragraphs
where either rule, or an invented actor under `PC-add-nothing`, had fired, at
`--repeat 3`. A control reran the same paragraphs with the unedited contract, because a
paragraph picked for a finding tends to show fewer findings on any rerun. Finding
counts are majority findings.

| Writer        | Arm            | Clean    | `PC-parallel-triads` findings | Invented-actor findings |
| ------------- | -------------- | -------- | ----------------------------- | ----------------------- |
| `opus` xhigh  | Control        | 35 of 57 | 13                            | 0                       |
| `opus` xhigh  | Edited, pass 1 | 44 of 57 | 3                             | 0                       |
| `opus` xhigh  | Edited, pass 2 | 48 of 57 | 3                             | 0                       |
| `sonnet` high | Control        | 16 of 57 | 9                             | 3                       |
| `sonnet` high | Edited, pass 1 | 21 of 57 | 2                             | 2                       |
| `sonnet` high | Edited, pass 2 | 18 of 56 | 0                             | 6                       |

The triad wording cut its findings for both writers against the control. The passive
wording showed no effect on invented actors. It stays because it removes a
contradiction between the rule's definition and its exemption.

## Adding a new slop sample

**One. Name the rule it violates.** Search inside `<prose-contract>` for a rule that
already covers it. Edit only `skills/prose/SKILL.md`, the source of truth. Most new
samples are an old pattern in a new surface form.

**Two. If no rule covers it, write the rule first.** A case with no rule behind it
grades nothing. A new rule needs a `PC-` id, a name, the markers that locate it, the
repair, an exemption, and a `[move N]` tag.

**Three. Write the rewrite row.** One sentence goes in `cases/sentences.csv`, a
multi-sentence sample in `cases/paragraphs.csv`, correspondence in
`cases/register.csv`, a judgment rule in `cases/judgment.csv`, everything else in
`cases/mechanics.csv`.

```csv
__description,polarity,bullet,input,__expected1,__expected2
"my-case-01","rewrite","PC-gnomic-restatement","The job dropped 400 rows. A pipeline that writes before it validates hands the next run a corrupt partition.","not-contains:A pipeline that","icontains:400"
```

Most rewrite rows want one `not-contains` proving the marker went away and one
`icontains` proving a fact survived. A rewrite that drops the defect by dropping the
content is a failure, and only the second assertion catches it.

**Four. Write at least one preserve row.** Every rule carries an exemption, so a
suite built only from defects trains an editor to delete on sight. Aim for three
preserve rows in every ten. The suite sits at 29 percent.

**Five. Run it and keep only what fails.** A case that passes on its first run
teaches nothing and costs a model call on every future run forever.

## Writing an assertion that survives a rewrite

Four traps make an assertion fail on a correct rewrite.

Matching an inflected word. A rewrite changes `flagging` to `flags`, so
`icontains:flagging` fails on correct output. Match the stem.

Demanding the deleted thing survive. `This is more than a runbook, it is an
operating model` becomes `This is an operating model`, and `icontains:runbook`
insists the foil stay. Assert on what the rewrite keeps.

Banning the fact instead of the defect. An empty-table case whose input reads `All
nine rows show a dash` still has to say the rows are empty. Ban the structure.

Escaping a regex through CSV. `regex:\\b(is|are)\\b` arrives as a literal backslash.
Prefer `contains` and `not-contains`.

## Graders

Three JavaScript graders in `defaultTest` run on every rewrite-suite case.

`banned-literals.js` fails on an em-dash, a spaced double hyphen, a semicolon, or
`load-bearing`. Those four are the only marks the contract bans with no exemption
anywhere, so they are the only ones safe to assert blindly.

`no-prose-colon.js` fails on any colon surviving after code fences, code spans,
URLs, clock times, and ratios are stripped.

`length-guard.js` fails a rewrite that grew past 1.1x its source, and only on
sources of 40 words or more. `MIN_WORDS` and `TOLERANCE` are guesses.

The compliance and generation loops carry one assertion, `graders/judge.js`, which
is the judge itself.

## Layout

| Path                            | Holds                                                                                        |
| ------------------------------- | -------------------------------------------------------------------------------------------- |
| `promptfooconfig.yaml`          | Rewrite suite: provider, shared graders, case files                                          |
| `promptfooconfig.comply.yaml`   | Compliance loop                                                                              |
| `promptfooconfig.generate.yaml` | Generation loop                                                                              |
| `promptfooconfig.pool.yaml`     | Pass one of corpus selection                                                                 |
| `prompts/`                      | The instructions wrapped around each case                                                    |
| `providers/`                    | `claude -p` wrappers                                                                         |
| `graders/`                      | JavaScript assertions for the rewrite suite                                                  |
| `cases/*.csv`                   | The rewrite suite, one row per case; `generate.csv` holds the 15 generation-loop fact sheets |
| `tools/`                        | Mining, selection, reporting, anchor checking, judge calibration                             |
| `corpus/`                       | Mined pages, selected paragraphs, notes, gitignored                                          |

## Judge calibration

`promptfooconfig.comply.rejudge.yaml` re-judges rewrites a previous run already
produced. `JUDGE_MODEL` and `JUDGE_EFFORT` pick the judge. Both judges see identical
text, so the only variable is the judge. Re-running the whole
pipeline would prove nothing, because the rewriter is non-deterministic and the two
judges would be scoring different text.

```bash
tools/rejudge-tests.py /tmp/run.json corpus/rejudge/comply.json
npx promptfoo@0.123.1 eval -c promptfooconfig.comply.rejudge.yaml --no-cache -o /tmp/rejudge-opus.json
JUDGE_MODEL=sonnet JUDGE_EFFORT=medium npx promptfoo@0.123.1 eval \
  -c promptfooconfig.comply.rejudge.yaml --no-cache -o /tmp/rejudge-sonnet.json
tools/judge-agreement.py across /tmp/rejudge-opus.json /tmp/rejudge-sonnet.json
tools/judge-agreement.py within /tmp/rejudge-sonnet.json
```

`across` reports clean-majority agreement and majority-finding agreement between the
two judges, with each rule's agree, a-only, and b-only counts. `within` reports clean
and finding agreement between one judge's passes.

Measured on 2026-09-26 by rejudging an earlier `opus` compliance run's rewrites, from
a writer at the CLI default effort, one per paragraph,
71 rows at 3 passes each. Each table row compares a judge with a first `opus` medium
rejudge, which called 54 of 71 rows clean for $25.91 in 53 seconds.

| Judge                     | Clean rows | Clean-majority agreement | Majority-finding agreement | Cost   | Time  |
| ------------------------- | ---------- | ------------------------ | -------------------------- | ------ | ----- |
| `opus` medium, second run | 54 of 71   | 67 of 71                 | 15 of 20                   | $25.94 | 45s   |
| `opus` high               | 49 of 71   | 62 of 71                 | 13 of 27                   | $27.22 | 53s   |
| `sonnet` medium           | 61 of 71   | 52 of 71                 | 2 of 24                    | $19.65 | 3m19s |

The second `opus` medium run sets the noise floor. `sonnet` falls far below it on
both measures and is not a substitute. `opus` high also falls below the floor. It
reported 9 majority findings the first medium run did not, against 5 the other way.
A hand review read the 14 majority findings where the first `opus` medium run and
`opus` high disagreed, against the catalog the judges used. 7 of the 9 findings only
high reported hold against the rule text. One does not, a single `PC-coordination`
hit that the rule's flag-by-density clause excludes. One is contested between
`PC-modifier-earns-place` and `PC-add-nothing`. 4 of the 5 findings only medium
reported hold, and one, a three-noun list under `PC-parallel-triads`, is contested.
High effort found more real violations at about the same precision, for $27.22
against $25.91 per 71 rows. 14 findings are too few to settle the default on their
own.

A majority of three passes repeats more often than a single pass. Two passes of the
first `opus` medium rejudge agreed on clean or dirty for 179 of 213 pass pairs, and
two passes of the second for 195 of 213. The majority verdict of three passes
repeated across the two runs on 67 of 71 rows.

## Mining candidates

`tools/mine-confluence.sh` pulls page bodies. `tools/judge-scan.sh` runs a judgment
pass over the chunked corpus, one rule group per call, writing candidates to
`corpus/candidates-<source>.jsonl`. Groups live in `tools/bullet-groups.json` and
carry `PC-` ids. No group holds more than seven rules, because grading each
dimension with an isolated judge beats one judge holding every dimension.

The miner runs one query per month rather than one for the window. A single
`created >= X ORDER BY created DESC` with a limit returns the newest N and nothing
else, so a year-long window produced a corpus spanning nine days.

One trap if you edit `judge-scan.sh`. The array is `BULLET_GROUPS` and never
`GROUPS`. Bash owns `GROUPS` as a special variable holding Unix group ids, so an
assignment to it yields a list of gids and a `mapfile` into it aborts the script
under `set -e` with nothing on stdout or stderr.

## Coverage

595 rewrite-suite cases across 56 rules, every one at ten or more, 29 percent
preserve rows. The compliance loop runs 71 paragraphs at three repeats, 213 calls.

Twenty of the 76 rules have no rewrite-suite case. `check-anchors.py` lists them and
does not fail, because a rule is allowed to exist before anyone writes a case.
