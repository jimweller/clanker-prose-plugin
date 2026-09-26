// The colon bullet bans the mark in every position and keeps only
// machine-readable text. strip-exempt removes that text, so any colon left in
// the output is a prose colon.
const { stripExempt } = require('./strip-exempt.js');

module.exports = (output) => {
  const text = stripExempt(String(output));
  const index = text.indexOf(':');

  if (index === -1) {
    return { pass: true, score: 1, reason: 'no prose colon' };
  }

  const start = Math.max(0, index - 40);
  const context = text.slice(start, index + 20).replace(/\s+/g, ' ').trim();
  return { pass: false, score: 0, reason: `prose colon near "${context}"` };
};
