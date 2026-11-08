'use strict';
/**
 * Pharmacy organisation service: Node.js + Express + SQLite (port 8004).
 *
 * One of the project's three languages: the hospital, specialist, gateway and broker are Python, the lab is Java, this is Node.js.
 * It keeps the same agreement (contract.xml) as every other organisation, so the gateway cannot tell which language is behind it:
 * REST + JSON, the shared service key, the "who is acting" headers, and messages through the broker.
 *
 *   POST /prescriptions            allergy + interaction check, answered at once (FR7, FR8)
 *   GET  /prescriptions            list, filter with ?patient_id= or ?status=
 *   PUT  /prescriptions/:id/dispense   dispense, and ask the hospital (by message) to close the case (FR9)
 *   POST|GET|PUT /pharmacists      the pharmacy's own staff
 */
const crypto = require('node:crypto');
const path = require('node:path');
const express = require('express');
const { loadConfig } = require('./src/config');
const { Store, HttpError, isDuplicate } = require('./src/store');
const { Relay } = require('./src/relay');
const { allergyWarning, interactionWarning } = require('./src/rules');

const KEY = process.env.PPS_SERVICE_KEY;
if (!KEY) { console.error('PPS_SERVICE_KEY is not set (python run.py sets it).'); process.exit(1); }

const xmlPath = path.join(__dirname, 'service.xml');
const cfg = loadConfig(xmlPath);
const store = new Store(cfg, process.env.PPS_DATA || __dirname);
const relay = cfg.messaging ? new Relay(store, cfg.messaging, KEY) : null;

function sameKey(given) {
  const a = Buffer.from(String(given || '')), b = Buffer.from(KEY);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

function actorOf(req) {   // the gateway says who is acting; services trust only the gateway
  const user = req.get('x-user');
  return user ? { user, role: req.get('x-role') || '' } : null;
}

// ---------------------------------------------------------------- business operations
const prescriptions = {
  /** FR7/FR8: record the prescription, with the allergy warning and the interaction check, and announce it. */
  create(body, actor) {
    return store.insert('prescriptions', body, {
      actor, stamps: ['doctor'], tag: 'POST /prescriptions',
      before: [
        (row) => { row.warning = allergyWarning(row.allergies, row.drug); },
        (row) => {
          const prior = store.all('SELECT drug FROM prescriptions WHERE patient_id=?', row.patient_id).map((r) => r.drug);
          row.interaction = interactionWarning(row.drug, prior, cfg.pairs);
        },
      ],
    });
  },
  /** FR9: dispensing marks it dispensed and, in the same transaction, queues the "close the case" message for the hospital. */
  dispense(id, body, actor) {
    return store.update('prescriptions', id, body, {
      actor, stamps: ['pharmacist'], set: { status: 'dispensed' }, tag: 'PUT /prescriptions/{id}/dispense',
    });
  },
};

// ---------------------------------------------------------------- HTTP
const app = express();
app.disable('x-powered-by');

app.use((req, res, next) => {   // only the gateway (and sibling services) may call a service; people use the portal
  if (!sameKey(req.get('x-service-key'))) {
    return res.status(401).json({ detail: 'Services accept requests from the gateway only. Use the portal.' });
  }
  next();
});
app.use(express.json({ type: () => true, limit: '1mb' }));

const handle = (fn) => async (req, res, next) => {
  try {
    const result = await fn(req);
    res.json(result);
    if (relay) relay.nudge();
  } catch (e) { next(e); }
};

app.get('/health', (req, res) => res.json({ ok: true }));

app.get('/', (req, res) => {
  res.json({
    service: cfg.name, port: cfg.port, database: cfg.db, language: 'Node.js (Express)',
    tables: Object.keys(cfg.tables).map((t) => ({
      table: t, records: store.count(t),
      open: (cfg.endpoints.find((e) => e.table === t && e.action === 'list') || {}).path || '',
    })),
    endpoints: cfg.endpoints.map((e) => ({ method: e.method, path: e.path, does: { list: 'List records', get: 'Get one record', insert: 'Create a record', update: 'Update a record' }[e.action] })),
    ...(cfg.messaging ? { messaging: {
      receives: cfg.messaging.consumes.map((c) => ({ queue: c.queue, handled_by: c.endpoint })),
      sends: cfg.messaging.sends.map((s) => ({ after: s.after, to: s.to, type: s.type || '', only_when: s.when || '' })),
      waiting_in_outbox: store.outboxSize(),
    } } : {}),
  });
});

app.post('/prescriptions', handle((req) => prescriptions.create(req.body || {}, actorOf(req))));
app.get('/prescriptions', handle((req) => store.list('prescriptions', req.query)));
app.put('/prescriptions/:id/dispense', handle((req) => prescriptions.dispense(req.params.id, req.body || {}, actorOf(req))));

app.post('/pharmacists', handle((req) => store.insert('staff', req.body || {}, { actor: actorOf(req) })));
app.get('/pharmacists', handle((req) => store.list('staff', req.query)));
app.put('/pharmacists/:id', handle((req) => store.update('staff', req.params.id, req.body || {}, { actor: actorOf(req) })));

app.use((err, req, res, next) => {   // eslint-disable-line no-unused-vars
  if (err instanceof HttpError) return res.status(err.status).json({ detail: err.detail });
  if (isDuplicate(err)) return res.status(409).json({ detail: 'record already exists' });
  if (err.type === 'entity.parse.failed') return res.status(400).json({ detail: 'the request body is not valid JSON' });
  console.error(err);
  res.status(500).json({ detail: 'internal error' });
});

const server = app.listen(cfg.port, '127.0.0.1', () => {
  console.log(`pharmacy service (Node ${process.versions.node}, Express) on http://localhost:${cfg.port}`);
});
if (relay) relay.run();

function shutdown() {
  if (relay) relay.stop();
  server.closeAllConnections();
  server.close(() => { store.close(); process.exit(0); });
  setTimeout(() => process.exit(0), 2000).unref();
}
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);
