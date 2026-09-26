// SKILL.md tells the editor to check that each rewrite is shorter than its
// source. The catalog measures that claim at page scale, where mechanical
// application "lengthened the tightest page in the set by 10 words", so the
// check only runs on paragraph-scale inputs. A sentence rewrite legitimately
// grows, because splitting one clause into two costs words.
//
// MIN_WORDS and TOLERANCE have no measurement behind them yet. Calibrate both
// once the suite has run against real Confluence pages.
const MIN_WORDS = 40;
const TOLERANCE = 1.1;

module.exports = (output, context) => {
  const source = String((context && context.vars && context.vars.input) || '');
  const count = (s) => s.trim().split(/\s+/).filter(Boolean).length;

  const before = count(source);
  const after = count(String(output));

  if (before === 0) {
    return { pass: false, score: 0, reason: 'no source text in vars.input' };
  }
  if (before < MIN_WORDS) {
    return { pass: true, score: 1, reason: `${before} words, below paragraph scale` };
  }

  const ratio = after / before;
  if (ratio <= TOLERANCE) {
    return { pass: true, score: 1, reason: `${before} words to ${after}` };
  }
  return {
    pass: false,
    score: 0,
    reason: `rewrite grew past ${TOLERANCE}x, ${before} words to ${after}`,
  };
};
