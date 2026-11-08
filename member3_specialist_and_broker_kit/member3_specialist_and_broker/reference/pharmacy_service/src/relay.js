'use strict';
// Outbox -> broker, in order. If the broker is down the messages simply wait in the pharmacy's own database.
class Relay {
  constructor(store, messaging, key) {
    this.store = store;
    this.url = messaging.broker.replace(/\/+$/, '');
    this.client = messaging.client;
    this.key = key;
    this.stopped = false;
    this.wake = null;
  }

  /** Tell the relay there is something new in the outbox. */
  nudge() { if (this.wake) this.wake(); }

  async send(spec) {
    return fetch(this.url + '/send', {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: 'application/json', 'x-service-key': this.key, 'x-client': this.client },
      body: JSON.stringify({ priority: 4, ttl_seconds: null, headers: {}, correlation_id: null, reply_to: null, ...spec }),
      signal: AbortSignal.timeout(10000),
    });
  }

  async flush() {
    for (const row of this.store.outboxBatch(100)) {
      const spec = JSON.parse(row.payload);
      try {
        const r = await this.send(spec);
        if (r.status >= 500) break;                    // broker trouble: keep it and try again
        if (r.status >= 400) {                          // refused for good (unknown destination, not allowed): do not block the line
          console.error(`[${this.client}] broker refused a message to ${spec.destination}: ${(await r.text()).slice(0, 120)}`);
        }
      } catch { break; }                                // broker unreachable: the message stays in the outbox
      this.store.outboxDelete(row.id);
    }
  }

  async run() {
    while (!this.stopped) {
      await new Promise((resolve) => { const t = setTimeout(resolve, 1000); this.wake = () => { clearTimeout(t); resolve(); }; });
      this.wake = null;
      try { await this.flush(); } catch (e) { console.error(`[${this.client}] outbox relay: ${e.message}`); }
    }
  }

  stop() { this.stopped = true; this.nudge(); }
}

module.exports = { Relay };
