'use strict';
// Reads service.xml: the tables, the messages to send and the drug-interaction pairs are declared there, exactly as in the other
// organisations' services. The endpoints and the business rules are written in JavaScript (server.js, rules.js).
const fs = require('node:fs');
const { XMLParser } = require('fast-xml-parser');

const LISTS = new Set(['table', 'send', 'consume', 'pair', 'endpoint']);

function loadConfig(xmlPath) {
  const parser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: '', isArray: (name, jpath, isLeaf, isAttribute) => !isAttribute && LISTS.has(name) });
  const root = parser.parse(fs.readFileSync(xmlPath, 'utf8')).service;
  const tables = {};
  for (const t of root.table || []) {
    const fields = {};
    for (const f of String(t.fields).split(',')) {
      const [name, ...rest] = f.split('=');
      fields[name.trim()] = rest.join('=');           // "status=pending" -> default "pending"; "drug" -> default ""
    }
    tables[t.name] = { fields, unique: t.unique || null };
  }
  const msg = root.messaging || null;
  return {
    name: root.name,
    port: Number(root.port),
    db: root.db,
    tables,
    endpoints: root.endpoint || [],
    pairs: ((root.interactions || {}).pair || []).map((p) => ({ a: p.a.toLowerCase(), b: p.b.toLowerCase(), level: p.level, note: p.note })),
    messaging: msg && {
      broker: msg.broker,
      client: msg.client,
      sends: (msg.send || []).map((s) => ({
        after: s.after, to: s.to, type: s.type || null, when: s.when || '', set: s.set || '', correlation: s.correlation || null,
        replyTo: s.reply_to || null, fields: String(s.fields || '').split(',').filter(Boolean),
      })),
      consumes: (msg.consume || []).map((c) => ({ queue: c.queue, endpoint: c.endpoint })),
    },
  };
}

module.exports = { loadConfig };
