'use strict';
// Unit tests for the pharmacy rules and the service.xml reader:   npm test      (node --test, no extra packages)
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { allergyWarning, interactionWarning } = require('../src/rules');
const { loadConfig } = require('../src/config');

const cfg = loadConfig(path.join(__dirname, '..', 'service.xml'));

test('allergy: a drug that contains an allergy word is flagged, whatever the letter case', () => {
  assert.equal(allergyWarning('penicillin', 'Penicillin V'), 'ALLERGY CONFLICT: penicillin');
  assert.equal(allergyWarning('Penicillin, sulfa', 'Sulfa-based tablet'), 'ALLERGY CONFLICT: sulfa');
});

test('allergy: no allergies, or no match, gives no warning', () => {
  assert.equal(allergyWarning('', 'Aspirin'), '');
  assert.equal(allergyWarning(null, 'Aspirin'), '');
  assert.equal(allergyWarning('penicillin', 'Aspirin 75 mg'), '');
});

test('interaction: warfarin with aspirin is MAJOR, in either order', () => {
  const a = interactionWarning('Warfarin 5 mg', ['Aspirin 75 mg'], cfg.pairs);
  const b = interactionWarning('Aspirin 75 mg', ['Warfarin 5 mg'], cfg.pairs);
  assert.match(a, /^MAJOR: Warfarin 5 mg with Aspirin 75 mg, higher risk of serious bleeding$/);
  assert.match(b, /^MAJOR: /);
});

test('interaction: nothing prescribed before, or unrelated drugs, gives no warning', () => {
  assert.equal(interactionWarning('Warfarin', [], cfg.pairs), '');
  assert.equal(interactionWarning('Paracetamol', ['Amoxicillin'], cfg.pairs), '');
});

test('interaction: the same pair reported twice is listed once', () => {
  const out = interactionWarning('Warfarin', ['Aspirin', 'Aspirin'], cfg.pairs);
  assert.equal(out.split('; ').length, 1);
});

test('service.xml: tables, messages and interaction pairs are read', () => {
  assert.equal(cfg.port, 8004);
  assert.deepEqual(Object.keys(cfg.tables), ['prescriptions', 'staff']);
  assert.equal(cfg.tables.prescriptions.fields.status, 'pending');
  assert.equal(cfg.tables.staff.unique, 'username');
  assert.ok(cfg.pairs.length >= 9);
  const closing = cfg.messaging.sends.find((s) => s.to === 'hospital.case-closed');
  assert.deepEqual(closing.fields, ['case_id']);
  assert.equal(closing.set, 'status=closed');
});
