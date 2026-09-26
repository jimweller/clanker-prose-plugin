// Marks with no exemption anywhere in the catalog. A hit is a failure whatever
// the sentence is doing, so these are the only literals safe in defaultTest.
//
// The LLM vocabulary list is deliberately absent. The catalog calls it the
// weakest bullet and exempts any word that names a thing in the system, so a
// blanket check on it would fail correct output.
const { stripExempt } = require('./strip-exempt.js');

const BANNED = [
  { name: 'em dash', re: /—/ },
  { name: 'double hyphen', re: /(?<![\w-])--(?![\w-])/ },
  { name: 'semicolon', re: /;/ },
  { name: 'load-bearing', re: /load[- ]bearing/i },
];

module.exports = (output) => {
  const text = stripExempt(String(output));
  const hits = BANNED.filter((b) => b.re.test(text)).map((b) => b.name);

  if (hits.length === 0) {
    return { pass: true, score: 1, reason: 'no unconditional marks' };
  }
  return {
    pass: false,
    score: 0,
    reason: `banned mark in output, ${hits.join(', ')}`,
  };
};
