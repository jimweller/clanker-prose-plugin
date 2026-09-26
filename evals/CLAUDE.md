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

| Knob                          | Default          | Effect                                                                                           |
| ----------------------------- | ---------------- | ------------------------------------------------------------------------------------------------ |
| `EVAL_MODEL`                  | `opus`           | Writer model alias                                                                               |
| `JUDGE_MODEL`, `JUDGE_EFFORT` | `opus`, `medium` | Judge model alias and effort                                                                     |
| `JUDGE_PASSES`                | 3                | Judge passes per row                                                                             |
| `JUDGE_MODE`                  | `whole`          | `groups` splits each pass into the four `tools/bullet-groups.json` groups plus a 54-id remainder |
| `JUDGE_CATALOG`               | unset            | Pins the judge to a catalog copy for an A/B                                                      |
| `JUDGE_MAX_PROCS`             | 96               | Concurrent judge processes per promptfoo run                                                     |
| `REWRITE_NOTES_DIR`           | `corpus/notes`   | Where the editor's notes land                                                                    |

Env beats config, which beats the default. `tools/comply-report.py` recomputes
every rate and exits 1 on a mismatch with promptfoo's derived metrics, a cached
row, a judge error, or a writer error. Findings are per row, by majority unless
`--findings union` is passed.

The editor writes its notes inside its own temp directory, and the provider copies
them to `REWRITE_NOTES_DIR`. Claude Code refuses a write inside a `--plugin-dir`
directory as a sensitive file, and `corpus/notes` sits inside the plugin.

`promptfooconfig.comply.rejudge.yaml` grades stored rewrites again without running
the writer. `tools/rejudge-tests.py` builds its tests from a prior `-o` JSON, and
`tools/judge-agreement.py` compares passes within a run, a run against the legacy
text judge, and two rejudges of the same text.

Measured on 2026-09-26, on the 71 first-repeat rewrites of the last legacy run.
The first two whole-mode rejudges ran before the catalog extraction was anchored, and
three stray lines of the skill's header reached the judge. The third column is the
fixed catalog and is the number to quote.

| Measure                                          | Whole, before fix | Whole, fixed | Groups, fixed |
| ------------------------------------------------ | ----------------- | ------------ | ------------- |
| Clean by majority                                | 69.0%, 70.4%      | 73.2%        | 42.3%         |
| Clean-majority agreement between two rejudges    | 64 of 71 (90%)    | not run      | not run       |
| Pass-vs-pass clean agreement                     | 83%               | 81%          | 79%           |
| Pass-vs-pass finding agreement                   | 41%               | 30%          | 45%           |
| Per-pass verdict agreement with the legacy judge | 70%               | 73%          | 55%           |
| Finding agreement with the legacy judge          | 15%               | 11%          | 7%            |
| Judge cost for 71 rows                           | $26               | $26          | $126          |

The legacy text judge scored the same 71 rewrites 71.8 percent clean. It ran on the
model before `opus` 5.5, so the agreement with it mixes a format change with a model
change.

Group mode stays opt-in. Its clean agreement did not beat whole mode by the 5 points
the plan required. It is the stricter instrument, though. On rows whole mode called
clean, 16 of 20 majority group findings read by hand hold against the rule text, and
the four that do not were `PC-landing-beats` three times and `PC-add-nothing` once.
Whole mode's clean rate therefore overstates compliance on these rewrites.

Parity with the legacy harness passed on 2026-09-26. The gate was two compliance runs
at `--repeat 3` within 7 points of a same-day legacy control, with classes ordered
`good`, `mixed`, `slop`. The class columns are clean by majority.

| Run            | Judged     | Clean by majority | Clean per pass | `good` | `mixed` | `slop` |
| -------------- | ---------- | ----------------- | -------------- | ------ | ------- | ------ |
| B              | 200 of 213 | 75.5%             | 73.3%          | 86%    | 74%     | 60%    |
| C              | 206 of 213 | 77.2%             | 75.1%          | 87%    | 77%     | 61%    |
| Legacy control | 213 of 213 | 70.4%             | 70.4%          | 84%    | 61%     | 65%    |

The legacy judge ran one pass per row, so its two rates are one number and the
per-pass rate is the like-for-like comparison. The 20 unjudged rows are
`reasoning_extraction` refusals. Run B still passed `--tools` to the writer, and both
runs predate the retry in `providers/writer.py`.

The generation writer uses `prompts/generate.txt`, which asks for no notes. The
`opus` 5.5 safeguard refused a version of it that asked for notes with
`reasoning_extraction` on 4 of 4 calls. Two runs of 15 sheets at `--repeat 3` scored 40.0 percent clean
before the catalog fix and 48.9 percent after it. Every one of the 90 writers loaded
the contract by following the plugin's `SessionStart` pointer with Read.

Concurrency measured at 6.2 cases per minute at `-j 24`, 10.7 at `-j 48`, and 20.3
at `-j 96`. A 213-call compliance arm runs in 5 to 6 minutes at 96. Load average
spikes near 140 on 14 cores for the first minute, which is 96 CLI processes
booting rather than contention, and settles near 45. 96 sessions hold 16.8 GB
resident, 175 MB each.

Foundry is not the limit. At `-j 96` the run draws roughly 1M input tokens per
minute against a 2M ITPM Opus allocation, and that count is pessimistic because it
charges the contract and the catalog on every call when both are cache reads after
the first, which ITPM excludes.

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

First measurement, 15 sheets at 3 repeats, 45 calls: 49 percent clean. The two largest
rule concentrations were `PC-add-nothing` (the writer drops a modal or a scoping
quantifier while compressing a hedged fact into a sentence) and `PC-leading-subordinate`.
The second one was a corpus defect, not a writer defect: all 15 sheets phrased their
hedged claim as "Whether X or Y ... has not been Z," a clausal subject, which is the
exact construction the rule bans, so the sheet itself handed the writer a violation to
carry through rather than testing whether the writer avoids one unprompted. All 15
were rewritten to extraposed form ("It has not been tested whether X or Y ...") or, in
one case, an if/then conditional, preserving every fact.

First fix, extraposing the hedge behind a dummy "it" ("It has not been tested whether
X"): still 49 percent clean (22/45). `PC-leading-subordinate` findings did not drop to
zero as expected; the judge held that a dummy-"it" subject still buries the predicate
and does not satisfy the rule's actual repair, which is to name a real subject, not
just relocate the clause. That reading is consistent with the rule's own text ("Put the
subject first"), so the first fix was incomplete rather than wrong. A different rule
also absorbed the same hedges in this run: `PC-name-the-uncertainty` appeared for the
first time, firing where the writer turned "it is not yet known whether X, or Y" into
"X may, or Y may," softening a named uncertainty into a modal.

Second fix, real subjects instead of a dummy "it" ("No test has confirmed whether X",
"The team does not yet know whether X"), plus two more baked-in patterns found the same
way and fixed the same way: `Root cause: X` (a label-colon prefix, in all five incident
sheets) and `Four Ns: A, B, C, and D` (a list-introducing colon in prose, `PC-colons`
bans this outright with no exemption, in all 15 sheets), and nine semicolon splices
(`PC-semicolons`, also banned outright) mostly in the "of those four, only A and B did
X" sentences. All three were sheet-authoring defects, not genuine tests: each handed the
writer a banned construction to carry through rather than testing composition.

Measured after all three sheet fixes, 45 calls each: 76 percent clean (34/45), then 67
percent (30/45) on a repeat, then 69 percent (31/45) after the single-line rewrite
below, averaging 71 percent against the original 49. That was a real, reproduced
improvement from the corpus fixes alone, unlike every contract-side edit attempted
earlier this session.

A second, larger jump followed a contract change: expanding `### Worked examples` from
one paragraph to three (see below). Measured twice on the live catalog, 45 calls each:
93 percent clean (42/45), then 78 percent (35/45), averaging about 86, both runs clearly
above the 71 percent plateau and at or above the 82 percent ceiling. The same expansion
measured on the compliance loop, pinned, moved nothing (66 percent, then 72, against 70
deployed, the same null result as the original single-example test). Comprehensive
worked examples help composition far more than editing: a rewrite anchors on the source
text already in front of the model, while generation has only the fact sheet and the
contract's worked examples to model good output on, so more of the latter helps more
here specifically. `PC-add-nothing` remained the leading rule in the corpus-fix-only
runs (tense and quantifier drift while compressing a fact sheet's bullet into a
sentence), consistent with every other arm, and dropped to at most one finding per run
once the worked examples expanded.

One judge-side artifact surfaced in both post-fix runs: `PC-round-trip-damage` fired
for "list markers collapsed into a paragraph," which is the generation task itself, not
a defect, since the judge cannot distinguish a fact sheet whose bullets were always
meant to become one paragraph from a real list an editor flattened by accident. Rather
than write a generation-aware judge prompt, which would break the same mechanics-only
discipline that keeps every other prompt honest, the sheets themselves were changed:
`cases/generate.csv` now holds each sheet as one line of period-separated fragments with
no bullet markers at all, so there is no list structure left to "collapse." A third
measurement after that change scored 69 percent clean (31/45) with zero
`PC-round-trip-damage` findings, confirming the fix. Three measurements now cluster at
67, 69, and 76 percent, averaging about 71, against the 49 percent baseline before any
of the three sheet-authoring defects were found. `cases/generate.csv` is single-line
fragments per sheet, not the bulleted form described earlier in this section.

## Where the numbers stand

|                                            | Clean     |
| ------------------------------------------ | --------- |
| Sources, judged with no edit at all        | 7%        |
| After the prose skill rewrites them        | 70%       |
| Ceiling, what a perfect editor could score | about 82% |

The source paragraphs are not compliant. Judging all 71 unmodified scores 7 percent
clean, and the `good` arm scores 0. Those are the paragraphs the contract was
written from, and "written from" is not "satisfies." Taking 7 to 70 is the measure
of what the contract does.

Split by class, on the current contract with the judge pinned to the pre-edit
catalog:

| Class        | Clean                                                                                                                      |
| ------------ | -------------------------------------------------------------------------------------------------------------------------- |
| `good`       | 83% (81% on the current, unpinned catalog)                                                                                 |
| `mixed`      | 67% (57% on the current, unpinned catalog)                                                                                 |
| `slop`       | 56% (54% on the current, unpinned catalog)                                                                                 |
| `generation` | 86% average (93%, 78%) after expanding the worked examples, up from 71% (corpus fixes alone) and 49% (baseline); see below |

The 83/67/56 figures were all measured with `JUDGE_CATALOG` pinned to a pre-edit
catalog, which is correct for an A/B but was never followed by a run against the
catalog a real, unpinned `/prose` invocation actually uses. That run happened once
this session: 65 percent clean overall (139/213), `good` 80, `mixed` 57, `slop` 54.
It is lower across every class than the pinned numbers, because a live catalog
grades with the contract's current, more specific rule text, which finds more of
what it is looking for. Treat 65/80/57/54 as the quotable numbers and the
pinned figures above as A/B baselines only.

`### Worked examples` in the contract expanded from one paragraph to three (a reply and
a report excerpt added, together with the original paragraph), raising the number of
rules demonstrated by an actual violated/not-violated table row from 20 of 76 to 61 of
76 (`check-anchors.py` reports the count). Measured on this loop, pinned, the expansion
moved nothing: 66 percent (141/213), then 72 (153/212), against 70 deployed-pinned,
inside the same noise band the original single example landed in. It was kept anyway,
because the same change produced the largest single result of the session on the
generation loop below.

### The target is 80 percent, not 95

A paragraph one judge pass calls clean is called clean again 82 percent of the
time, 14 of 17 measured on identical re-judges. The judge spuriously flags about
one clean paragraph in six, so a perfect editor producing perfectly compliant prose
still caps near 82 on this instrument. The noise runs both ways: a paragraph called
dirty comes back clean on a second pass 8 times in 31.

Treat any run above 78 percent as at the ceiling rather than as an improvement.
Targeting 90 or 95 means targeting a number the instrument cannot produce, and the
only way to reach it is to make the judge less strict, which is not the same as
better prose.

Two ways to raise the ceiling itself, neither tried. Run the judge more than once
per case and take a majority, which trades runtime for precision and is cheap at
`-j 96`. Or narrow what the judge grades, since it holds all 76 rules at once and
Anthropic's own guidance is that an isolated judge per dimension beats one judge
holding every dimension.

## What this instrument can and cannot measure

**Only the clean rate is reliable.** Re-judging 48 stored rewrites with the same
model and settings agreed on 39 percent of individual findings and 81 percent of
clean-or-dirty verdicts. Per-rule counts below about five are inside that noise.
On a 213-run arm, roughly 40 runs can flip between two identical runs, so a
movement smaller than that is not a result.

**Judge passes are a recall mechanism.** One pass finds about 39 percent of what a
second pass finds. The legacy report took the union of findings across three
repeats, which were three different rewrites of one case. The promptfoo judge runs
three passes on one rewrite instead, and `comply-report.py` keeps a finding when a
majority of those passes report it, or any pass with `--findings union`.

**Both sides read the same contract**, so sharpening a rule teaches the judge what
to look for at the same moment it instructs the editor. Adding a modality clause to
`PC-add-nothing` raised its finding count, and one finding cited the new clause by
name while faulting the editor. That was a detector, not a repair. For an A/B, copy
the pre-edit catalog aside and point `JUDGE_CATALOG` at it, which pins the grader
so any movement is the editor.

```bash
cp corpus/catalog.md /tmp/catalog-pinned.md
# edit the contract
JUDGE_CATALOG=/tmp/catalog-pinned.md npx promptfoo@latest eval \
  -c promptfooconfig.comply.yaml --repeat 3 -j 96 -o /tmp/after.json
```

**Run an A/B twice before believing it.** The first pinned-judge A/B moved clean
from 62 to 66 percent, which is inside the noise. The repeat landed at 70, and the
two post-edit runs agreed with each other more closely than either agreed with the
baseline, which is what made the movement credible. One run is a direction, two are
a result.

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

**Hooks.** On one 213-call run the claude-mem worker went unreachable for 65
consecutive hooks, and some sessions returned the block banner in place of a
rewrite, which the judge graded as prose. That produced 10 `PC-assistant-tool-leaks`
findings and 21 runs with no notes file. `providers/writer.py` now runs the rewriter
with `--setting-sources "" --plugin-dir <this plugin root>`, which drops every
machine-level setting, including the hooks that caused the failure, and loads only
this plugin. The contract and the skill are the same file, `skills/prose/SKILL.md`;
the plugin's `SessionStart` hook points the rewriter at it and the rewriter reads it
directly, rather than relying on a `~/.claude/CLAUDE.md` symlink resolving as a
project source.

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
authored prose, they score about 10 points worse on the clean rate, and a prose
contract has no business being measured on them. Also excluded: Jira ADF JSON dumps,
UUID action-item lists, testimonial quotes, and PRD boilerplate that appeared
verbatim on three separate pages.

Everything under `corpus/` is gitignored and stays that way. Both repos holding this
suite are public, so mined page bodies never get committed. A case reaching
`cases/*.csv` is written fresh over invented facts.

## Rule ids

Every rule opens with a `PC-` id, 76 in total, 55 in `Banned Patterns` and 21 in
`Ghostwriting`. The five moves in `How to Write` keep their `[move N]` tags, which
already cross-reference from every banned-pattern rule.

Free-text rule names did not survive two sessions. One run scored
`trailing supplements` and `trailing supplements that hang a second beat on a
finished clause` as two rules at 3 each instead of one at 6, and did that to three
rules. An id is either in the contract or it is not, so `comply-report.py` reports
any finding citing an id the contract does not define.

`tools/check-anchors.py` fails on an unknown id, a rule with no id or two, a
duplicate id, a `[move N]` pointing at nothing, and a `corpus/catalog.md` whose
content differs from the contract. That last check exists because the provider
rebuilds the catalog on an `mtime` comparison, which a `git checkout` defeats.

Watch for terms the callers use that the contract never defines. `style-rule`
appeared once in the judge prompt carrying the definition of a violation, and zero
times in the contract, so the judge had to infer it. Same defect as
`house prose contract`, which the contract also never answered to.

## Measuring a rule change

One pass per case cannot tell a rule improvement from model variance. Three full
runs of the rewrite suite scored 94, 97 and 96 percent, and between two of them
`praise adjectives` fell from 100 to 70 on cases nobody had touched.

On 2026-09-26 the plugin delivery scored 93.3 and 92.9 percent at `--repeat 1`. A
same-day control with the pre-cut `claude_md.md` loaded as user memory and the
pre-move skill scored 95.0 percent. The per-case paired difference is -1.9 points
(t about -2.7 over 595 cases). The banned-literals grader failed on no row in any of
the three runs. A fourth arm, the plugin plus the contract preloaded as user memory,
scored 93.9 percent. It sits 0.8 points above the plugin (t 0.98) and 1.0 below the
control (t 1.10), so the delivery channel accounts for about half the gap and the rest
of the old instructions and skill wording for the other half, neither half
significant alone.

```bash
tools/measure-bullet.sh gnomic- before
# edit skills/prose/SKILL.md
tools/measure-bullet.sh gnomic- after
```

That runs five repeats per case and prints the delta split by polarity. Read the two
arms rather than the overall number, because most contract edits move them in
opposite directions. Telling an editor to cut harder raises the rewrite arm and
lowers the preserve arm.

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

On the first full run, 36 of 595 cases failed and most were the assertion rather
than the rule. Four traps produced nearly all of them.

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

`across` reports clean-majority agreement between the two judges. `within` reports
clean and finding agreement between one judge's passes. No mode compares findings
across two judges.

The table below was measured on the legacy text judge, against a 39 percent finding-level and 81 percent clean-or-dirty noise
floor.

| Judge                    | Finding-level | Clean or dirty |
| ------------------------ | ------------- | -------------- |
| Opus, identical settings | 39%           | 81%            |
| Opus, medium effort      | 30%           | 79%            |
| Sonnet, default          | 21%           | 67%            |
| Sonnet, medium           | 20%           | 60%            |

Opus at medium sits inside the floor and cannot be shown to differ, so the judge
runs at medium effort. Sonnet is clearly below it and is not a substitute at any
effort.

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

## Open

**The 70 percent is attributed to the trims, not the worked paragraph.** Three
contract changes landed in the same A/B: the worked paragraph, the `PC-emdashes`
trim, and the `PC-evidential-status` compression. Removing the worked paragraph and
re-running the compliance loop with the judge pinned to the same pre-edit catalog
scored 69 percent clean (146/213), against 70 percent (149/213) with the paragraph
in. That is inside the roughly-40-run noise band on a 213-run arm, so the paragraph
carries none of the measured gain; the trims do. Next edits should trim the other
overloaded rules rather than write more worked paragraphs.

**The quotable number is now measured: 65 percent, not 70.** Running the compliance
loop with no `JUDGE_CATALOG` pin, so the judge grades against the live, current
catalog the way a real `/prose` invocation would, scored 65 percent clean overall
(139/213): `good` 80, `mixed` 57, `slop` 54. Every pinned A/B in this doc, including
the 83/67/56 split, used a catalog frozen before the worked-paragraph and
`PC-emdashes`/`PC-evidential-status` edits, which undercounts what the current,
more specific rule text actually catches. The pinned numbers stay correct for
measuring an edit's direction; they are not the number to quote for where the
contract stands today.

**The `good` arm damages about one run in six.** The diagnosis is specific and not
what it looks like. The editor is not over-applying there. It is editing text that
needed no edit and introducing defects doing it: a trailing anaphor, a gerund
subject, a nominalization in the subject slot, a reassigned attribution. That points
at a missing stop condition rather than a wrong rule.

**`PC-add-nothing` leads every run** at 28 of 74 findings, almost all self-inflicted.
The editor drops modals, tenses and scoping quantifiers, turning "worked that day"
into "were working" and "sometimes for days or even weeks" into "for days or even
weeks." A modality clause was added to the rule and did not move the number.

**Tightening `PC-parallel-triads`'s exemption did not move the number.** The rule was
the second-largest concentration after `PC-add-nothing`, 11 findings, 5 of them
`held-then-violation`: the editor invoked the exemption and the judge rejected it,
which pointed at a genuinely circular criterion ("keep the triad when the split
would produce [the uniformity that is the reason to split]"). Replaced it with a
concrete test, an inherent order in the source versus cadence with no such order.
Pinned A/B against the same pre-worked-paragraph catalog used for the 70 percent
measurement: 65 percent clean (138/213) against 70 percent deployed, a 5-point move
on a 213-run arm, inside the roughly-40-run noise band. Reverted rather than spend a
second run confirming a null result. The disagreement between editor and judge on
this rule is real and unresolved; rewriting the exemption's wording did not reach it.

**Fleshing out `PC-vague-claims` did not move the number either, and risked a worse
defect.** The rule was a one-line stub with no markers or exemption, unlike its 45
siblings ("vague claims without evidence [move 2]"). Expanded it to name markers
("several teams noticed", "some improvement") and to instruct naming the count,
comparison, or instance, or saying plainly that none exists. Pinned A/B against the
same catalog: 67 percent clean (143/213) against 70 percent deployed, inside the
noise band, with `slop` moving 56 to 44 and `mixed` 67 to 62. `PC-add-nothing`'s
count rose in the same run, consistent with the writer inventing a number to satisfy
"name the count" where the fact sheet or source supplied none, fighting the rule
that already bans that. Reverted. A vague rule may still be underspecified, but
telling the writer to be specific is not a safe fix on its own without also
strengthening the "say so plainly" branch enough to out-compete it.

**A self-review pass in the prose skill did not move the number.** All three edits
above changed contract wording; this one changed the mechanism instead, on the
theory that a single-pass rewrite with no verification step is inherently noisy.
`SKILL.md` went from "rewrite, then print" to "draft, reread once sentence by
sentence against the contract, then print." Pinned A/B: 65 percent clean (138/213)
against 70 percent deployed, inside the noise band, with every class flat or down
(`good` 83->75, `mixed` 67->63, `slop` 56->50). Reverted. Four edit attempts across
two sessions, three on rule text and one on the skill's mechanism, have now each
landed inside the same noise band. That is itself the finding: at this sample size
(213 runs, ~40-run noise band) neither a contract edit nor a mechanism edit has yet
produced a measurable movement, so the next attempt needs to either raise the
sample size, reduce judge noise (majority-vote or per-dimension judging, both
already listed above as untried), or accept that 67/56/49 may be closer to this
population's true rate than to something four small edits can lift.
