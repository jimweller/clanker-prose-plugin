'use strict';
const fs = require('node:fs');

const WHOLE_SCOPE = 'against every rule in the contract';

function loadGroups(file) {
  const raw = JSON.parse(fs.readFileSync(file, 'utf8'));
  return Object.fromEntries(Object.entries(raw).filter(([k]) => !k.startsWith('_')));
}

// Group mode judges the themed groups from bullet-groups.json plus one unit holding
// every id they leave out, so each contract id is judged exactly once per pass.
function buildUnits({ mode, catalogIds, groups }) {
  if (mode === 'whole') return [{ name: 'whole', ids: [...catalogIds].sort(), scope: WHOLE_SCOPE }];
  if (mode !== 'groups') throw new Error(`judge mode must be whole or groups, got ${JSON.stringify(mode)}`);
  const known = new Set(catalogIds);
  const owner = new Map();
  const units = [];
  for (const [name, ids] of Object.entries(groups)) {
    for (const id of ids) {
      if (!known.has(id)) throw new Error(`group ${name} names ${id}, which the contract does not define`);
      if (owner.has(id)) throw new Error(`${id} sits in more than one group (${owner.get(id)}, ${name})`);
      owner.set(id, name);
    }
    units.push({ name, ids: [...ids].sort() });
  }
  const rest = catalogIds.filter((id) => !owner.has(id)).sort();
  if (rest.length > 0) units.push({ name: 'remainder', ids: rest });
  return units.map((u) => ({ ...u, scope: `against these rules only, and report no other rule: ${u.ids.join(', ')}` }));
}

module.exports = { loadGroups, buildUnits, WHOLE_SCOPE };
