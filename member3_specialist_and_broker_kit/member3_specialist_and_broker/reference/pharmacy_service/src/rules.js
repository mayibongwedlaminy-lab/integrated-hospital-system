'use strict';
// The pharmacy's business rules (FR8). Pure functions: no database, no network, so they are easy to test.

/** Allergy check: any allergy word contained in the drug name raises a warning. */
function allergyWarning(allergies, drug) {
  const name = String(drug ?? '').toLowerCase();
  const hits = String(allergies ?? '').split(',').map((a) => a.trim()).filter((a) => a && name.includes(a.toLowerCase()));
  return hits.length ? 'ALLERGY CONFLICT: ' + hits.join(', ') : '';
}

/** Interaction check: the new drug against everything already prescribed to the same patient. A drug matches a pair by containing its word. */
function interactionWarning(drug, priorDrugs, pairs) {
  const found = [];
  const fresh = String(drug ?? '').toLowerCase();
  for (const p of pairs) {
    for (const other of priorDrugs) {
      const old = String(other ?? '').toLowerCase();
      if ((fresh.includes(p.a) && old.includes(p.b)) || (fresh.includes(p.b) && old.includes(p.a))) {
        found.push(`${p.level.toUpperCase()}: ${drug} with ${other}, ${p.note}`);
      }
    }
  }
  return [...new Set(found)].join('; ');
}

module.exports = { allergyWarning, interactionWarning };
