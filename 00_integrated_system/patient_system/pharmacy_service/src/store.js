'use strict';
// This organisation's own database (SQLite, pharmacy.db) and the transactional outbox.
// A record and the messages that announce it are saved in ONE transaction: either both exist or neither does.
const fs = require('node:fs');
const path = require('node:path');
const { DatabaseSync } = require('node:sqlite');

class HttpError extends Error {
  constructor(status, detail) { super(detail); this.status = status; this.detail = detail; }
}

/** Matches "field=value,field!=value" like the other services' <send when="...">. "field!=" means: not empty. */
function matches(cond, row) {
  for (const c of String(cond || '').split(',').map((x) => x.trim()).filter(Boolean)) {
    const i = c.indexOf('=');
    const k = c.slice(0, i), v = c.slice(i + 1);
    if (k.endsWith('!') ? String(row[k.slice(0, -1)] ?? '') === v : String(row[k] ?? '') !== v) return false;
  }
  return true;
}

/** Everything is stored as TEXT, as in the other services, so a number sent as 7 and a string sent as "7" are the same record. */
function asText(v, field) {
  if (v === null) return null;
  if (typeof v === 'string') return v;
  if (typeof v === 'number') return String(v);
  if (typeof v === 'boolean') return v ? '1' : '0';
  throw new HttpError(422, `'${field}' must be text or a number`);
}

class Store {
  constructor(cfg, dataDir) {
    this.cfg = cfg;
    fs.mkdirSync(dataDir, { recursive: true });
    this.db = new DatabaseSync(path.join(dataDir, cfg.db));
    this.db.exec('PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=10000;');
    for (const [name, t] of Object.entries(cfg.tables)) {
      const cols = Object.keys(t.fields).map((k) => `${k} TEXT`).join(', ');
      this.db.exec(`CREATE TABLE IF NOT EXISTS ${name} (id INTEGER PRIMARY KEY AUTOINCREMENT, ${cols}, created TEXT DEFAULT CURRENT_TIMESTAMP${t.unique ? `, UNIQUE(${t.unique})` : ''})`);
    }
    if (cfg.messaging) {
      this.db.exec('CREATE TABLE IF NOT EXISTS _outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP)');
    }
  }

  close() { this.db.close(); }

  all(sql, ...args) { return this.db.prepare(sql).all(...args).map((r) => ({ ...r })); }

  one(table, id) {
    const rows = /^\d+$/.test(String(id)) ? this.all(`SELECT * FROM ${table} WHERE id=?`, Number(id)) : [];
    if (!rows.length) throw new HttpError(404, `${table} ${id} not found`);
    return rows[0];
  }

  list(table, query = {}) {
    const known = this.cfg.tables[table].fields;
    const f = Object.entries(query).filter(([k]) => k in known).map(([k, v]) => [k, String(Array.isArray(v) ? v[0] : v)]);
    const where = f.length ? ' WHERE ' + f.map(([k]) => `${k}=?`).join(' AND ') : '';
    return this.all(`SELECT * FROM ${table}${where}`, ...f.map(([, v]) => v));
  }

  /** Run fn inside one transaction. */
  atomically(fn) {
    this.db.exec('BEGIN IMMEDIATE');
    try { const out = fn(); this.db.exec('COMMIT'); return out; } catch (e) { this.db.exec('ROLLBACK'); throw e; }
  }

  /** Build the messages <send after="METHOD /path"> asks for and put them in the outbox (call inside atomically()). */
  announce(tag, result) {
    for (const s of this.cfg.messaging ? this.cfg.messaging.sends : []) {
      if (s.after !== tag || !matches(s.when, result)) continue;
      const body = Object.fromEntries((s.fields.length ? s.fields : Object.keys(result)).map((f) => [f, result[f] ?? null]));
      for (const kv of s.set.split(',').filter(Boolean)) { const [k, ...v] = kv.split('='); body[k] = v.join('='); }
      const spec = {
        destination: s.to, body, headers: s.type ? { type: s.type } : {},
        correlation_id: s.correlation ? String(result[s.correlation]) : null, reply_to: s.replyTo,
      };
      this.db.prepare('INSERT INTO _outbox (payload) VALUES (?)').run(JSON.stringify(spec));
    }
  }

  insert(table, body, { actor, stamps = [], before = [], tag }) {
    return this.atomically(() => {
      const row = {};
      for (const [k, d] of Object.entries(this.cfg.tables[table].fields)) row[k] = k in body ? asText(body[k], k) : d;
      if (actor) for (const col of stamps) row[col] = actor.user;
      for (const hook of before) hook(row);
      const keys = Object.keys(row);
      const info = this.db.prepare(`INSERT INTO ${table} (${keys.join(',')}) VALUES (${keys.map(() => '?').join(',')})`).run(...Object.values(row));
      const result = this.one(table, Number(info.lastInsertRowid));
      if (tag) this.announce(tag, result);
      return result;
    });
  }

  update(table, id, body, { actor, stamps = [], set = {}, tag }) {
    return this.atomically(() => {
      const existing = this.one(table, id);
      const known = this.cfg.tables[table].fields;
      const changes = {};
      for (const [k, v] of Object.entries(body)) if (k in known) changes[k] = asText(v, k);
      Object.assign(changes, set);
      if (actor) for (const col of stamps) changes[col] = actor.user;
      const changed = Object.entries(changes).filter(([k, v]) => v !== existing[k]);
      if (changed.length) {
        this.db.prepare(`UPDATE ${table} SET ${changed.map(([k]) => k + '=?').join(',')} WHERE id=?`).run(...changed.map(([, v]) => v), existing.id);
      }
      const result = this.one(table, id);
      if (tag) this.announce(tag, result);
      return result;
    });
  }

  count(table) { return this.all(`SELECT COUNT(*) AS n FROM ${table}`)[0].n; }

  outboxBatch(limit = 100) { return this.all('SELECT id, payload FROM _outbox ORDER BY id LIMIT ?', limit); }
  outboxDelete(id) { this.db.prepare('DELETE FROM _outbox WHERE id=?').run(id); }
  outboxSize() { return this.cfg.messaging ? this.count('_outbox') : 0; }
}

function isDuplicate(err) {
  return /UNIQUE constraint failed/i.test(String(err && err.message));
}

module.exports = { Store, HttpError, isDuplicate };
