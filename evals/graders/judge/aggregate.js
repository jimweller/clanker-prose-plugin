'use strict';

function majority(p) {
  return Math.floor(p / 2) + 1;
}

const bit = (b) => (b ? 1 : 0);

// A finding key is (kind, rule) for prose and rule alone for the register. Spans
// drift between passes, so they are reported per pass but never part of the key.
function keyOf(finding) {
  return finding.kind ? `${finding.kind}:${finding.rule}` : finding.rule;
}

function aggregateFindings({ prefix, passes, ids, perRule = false, kinds = false, rowClass, classes }) {
  const p = passes.length;
  const m = majority(p);
  const clean = passes.map((pass) => pass.findings.length === 0);
  const cleanCount = clean.filter(Boolean).length;
  const cleanMaj = cleanCount >= m;

  const byKey = new Map();
  passes.forEach((pass, passIndex) => {
    const seen = new Set();
    for (const finding of pass.findings) {
      const key = keyOf(finding);
      if (!byKey.has(key)) byKey.set(key, { key, rule: finding.rule, kind: finding.kind, votes: 0, passes: [] });
      const entry = byKey.get(key);
      if (!seen.has(key)) {
        entry.votes += 1;
        seen.add(key);
      }
      entry.passes.push({ pass_index: passIndex, span: finding.span, why: finding.why });
    }
  });

  const namedScores = {
    [`${prefix}_judged`]: 1,
    [`${prefix}_judge_error`]: 0,
    [`${prefix}_passes`]: p,
    [`${prefix}_pass_clean`]: cleanCount,
    [`${prefix}_clean_maj`]: bit(cleanMaj),
    [`${prefix}_clean_union`]: bit(cleanCount === p),
    [`${prefix}_pass_agree`]: bit(cleanCount === 0 || cleanCount === p),
  };

  if (kinds) {
    const passesWith = (kind) => passes.filter((pass) => pass.findings.some((f) => f.kind === kind)).length;
    namedScores[`${prefix}_viol_maj`] = bit(passesWith('violation') >= m);
    namedScores[`${prefix}_over_maj`] = bit(passesWith('over-applied') >= m);
  }

  if (perRule) {
    for (const id of ids) {
      const entry = byKey.get(id);
      namedScores[`R:${id}`] = bit(entry !== undefined && entry.votes >= m);
    }
  }

  if (rowClass !== undefined) {
    if (!classes || !classes.includes(rowClass)) throw new Error(`row class ${JSON.stringify(rowClass)} is not one of ${JSON.stringify(classes)}`);
    for (const c of classes) {
      namedScores[`${prefix}_judged_${c}`] = bit(c === rowClass);
      namedScores[`${prefix}_clean_maj_${c}`] = bit(c === rowClass && cleanMaj);
    }
  }

  const entries = [...byKey.values()].sort((a, b) => b.votes - a.votes || a.key.localeCompare(b.key));
  const componentResults = entries.map((e) => ({
    pass: e.votes < m,
    score: e.votes < m ? 1 : 0,
    reason: `${e.key} flagged by ${e.votes}/${p} passes (majority ${m})`,
    metadata: { role: 'finding', key: e.key, rule: e.rule, kind: e.kind || null, votes: e.votes, passes_total: p, majority: e.votes >= m, passes: e.passes },
  }));

  const flagged = entries.map((e) => `${e.key} ${e.votes}/${p}`).join(', ');
  return {
    pass: cleanMaj,
    score: bit(cleanMaj),
    reason: `${prefix} clean in ${cleanCount}/${p} passes (majority ${m})${flagged ? `: ${flagged}` : ''}`,
    namedScores,
    componentResults,
  };
}

function aggregateVerdicts({ prefix, passes }) {
  const p = passes.length;
  const m = majority(p);
  const votes = passes.filter((v) => v.verdict === 'pass').length;
  const passMaj = votes >= m;
  return {
    pass: passMaj,
    score: bit(passMaj),
    reason: `${prefix} pass in ${votes}/${p} passes (majority ${m})`,
    namedScores: {
      [`${prefix}_judged`]: 1,
      [`${prefix}_judge_error`]: 0,
      [`${prefix}_passes`]: p,
      [`${prefix}_pass_votes`]: votes,
      [`${prefix}_pass_maj`]: bit(passMaj),
    },
    componentResults: passes.map((v, i) => ({
      pass: v.verdict === 'pass',
      score: bit(v.verdict === 'pass'),
      reason: `pass ${i}: ${v.verdict}: ${v.reason}`,
      metadata: { role: 'verdict', pass_index: i, verdict: v.verdict, reason: v.reason },
    })),
  };
}

function judgeError({ prefix, message }) {
  return {
    pass: false,
    score: 0,
    reason: `JUDGE_ERROR: ${message}`,
    namedScores: { [`${prefix}_judge_error`]: 1 },
    componentResults: [],
  };
}

module.exports = { majority, keyOf, aggregateFindings, aggregateVerdicts, judgeError };
