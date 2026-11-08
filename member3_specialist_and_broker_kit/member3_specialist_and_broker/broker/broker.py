"""Message broker with JMS-style semantics, in one file.

Queues (point-to-point) and topics (publish/subscribe with durable subscriptions). A message is saved before the sender is told
it was accepted; a consumer must acknowledge each message or it is delivered again; after too many failed deliveries a message
goes to the dead-letter list, where an administrator can retry it. Destinations and who may use them are in broker.xml.

The wire protocol is plain HTTP + JSON, so a Python service, the Java analyzer or curl can all be clients.
Every call needs  x-service-key  (shared secret) and  x-client  (who is calling)."""
import asyncio, hmac, json, os, sqlite3, sys, time
import xml.etree.ElementTree as ET
from contextlib import closing
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "engine"))
from pages import nice  # noqa: E402

KEY = os.environ.get("PPS_SERVICE_KEY") or sys.exit("PPS_SERVICE_KEY is not set (python run.py sets it).")
cfg = ET.parse(os.path.join(HERE, "broker.xml")).getroot()
S = cfg.find("settings")
VISIBILITY, RETRY_DELAY = float(S.get("visibility_seconds")), float(S.get("retry_delay_seconds"))
MAX_DELIVERIES, KEEP = int(S.get("max_deliveries")), float(S.get("keep_done_hours")) * 3600
names = lambda text: {x.strip() for x in (text or "").split(",") if x.strip()}
ADMIN = names(cfg.get("admin"))
DATA = os.environ.get("PPS_DATA") or HERE
os.makedirs(DATA, exist_ok=True)
DB = os.path.join(DATA, cfg.get("db"))

DEST, TOPICS = {}, {}  # DEST: queue or "topic:subscription" -> rules; TOPICS: topic -> senders and subscriptions
for q in cfg.findall("queue"):
    DEST[q.get("name")] = {"kind": "queue", "send": names(q.get("send")), "receive": names(q.get("receive")), "doc": q.get("doc", "")}
for t in cfg.findall("topic"):
    TOPICS[t.get("name")] = {"send": names(t.get("send")), "subs": []}
    for s in t.findall("subscription"):
        sub = f"{t.get('name')}:{s.get('name')}"
        DEST[sub] = {"kind": "subscription", "send": names(t.get("send")), "receive": names(s.get("receive")), "doc": f"Durable subscription on topic {t.get('name')}"}
        TOPICS[t.get("name")]["subs"].append(sub)


def conn():
    c = sqlite3.connect(DB, timeout=10, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA synchronous=NORMAL")
    return c


with closing(conn()) as c:
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, destination TEXT NOT NULL, body TEXT NOT NULL, headers TEXT NOT NULL DEFAULT '{}',
        correlation_id TEXT, reply_to TEXT, sender TEXT, priority INTEGER DEFAULT 4, created REAL, available_at REAL, expires_at REAL,
        state TEXT NOT NULL DEFAULT 'ready', deliveries INTEGER DEFAULT 0, visible_at REAL, consumer TEXT, reason TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS ix_dest ON messages (destination, state, available_at)")


def client_of(request):
    return request.headers.get("x-client", "")


def allowed(request, group):
    return "*" in group or client_of(request) in group


def selector_ok(headers, selector):  # "type=LabResultReady,priority=high": every pair must match a header exactly
    pairs = (p.partition("=") for p in selector.split(",") if p.strip())
    return all(str(headers.get(k.strip(), "")) == v.strip() for k, _, v in pairs)


def view(r):
    return {"id": r["id"], "destination": r["destination"], "body": json.loads(r["body"]), "headers": json.loads(r["headers"]),
            "correlation_id": r["correlation_id"], "reply_to": r["reply_to"], "sender": r["sender"], "priority": r["priority"],
            "deliveries": r["deliveries"], "state": r["state"], "reason": r["reason"], "created": r["created"]}


app = FastAPI(title="Message broker")


@app.middleware("http")  # services, the gateway and the analyzer only; people use the portal
async def guard(request, call_next):
    if not hmac.compare_digest(request.headers.get("x-service-key", ""), KEY):
        return JSONResponse({"detail": "The broker accepts calls from the system's own components only. Use the portal."}, 401)
    return await call_next(request)


app.middleware("http")(nice)


@app.post("/send")
async def send(request: Request):
    b = await request.json()
    dest = b.get("destination")
    if dest in TOPICS:
        rules, targets = TOPICS[dest], TOPICS[dest]["subs"]  # a topic copies the message into every durable subscription
    elif dest in DEST and DEST[dest]["kind"] == "queue":
        rules, targets = DEST[dest], [dest]
    else:
        raise HTTPException(404, f"No such destination: {dest}")
    if not allowed(request, rules["send"]):
        raise HTTPException(403, f"'{client_of(request)}' may not send to {dest}")
    now, ttl = time.time(), b.get("ttl_seconds")
    ids = []
    with closing(conn()) as c:
        for t in targets:
            cur = c.execute(
                "INSERT INTO messages (destination, body, headers, correlation_id, reply_to, sender, priority, created, available_at, expires_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (t, json.dumps(b.get("body")), json.dumps(b.get("headers") or {}), b.get("correlation_id"), b.get("reply_to"),
                 client_of(request), int(b.get("priority", 4)), now, now, now + float(ttl) if ttl else None))
            ids.append(cur.lastrowid)
        c.execute("DELETE FROM messages WHERE state='done' AND created<?", (now - KEEP,))
    return {"id": ids[0] if ids else None, "delivered_to": len(ids)}


def claim(dest, selector, client):
    """Hand out the best waiting message (highest priority, then oldest) and make it invisible to others until acknowledged."""
    now = time.time()
    with closing(conn()) as c:
        c.execute("BEGIN IMMEDIATE")
        try:
            c.execute("UPDATE messages SET state='dead', reason='expired' WHERE destination=? AND state IN ('ready','inflight') AND expires_at<=?", (dest, now))
            c.execute("UPDATE messages SET state='ready', available_at=? WHERE destination=? AND state='inflight' AND visible_at<=?", (now, dest, now))  # never acknowledged: offer again
            rows = c.execute("SELECT * FROM messages WHERE destination=? AND state='ready' AND available_at<=? ORDER BY priority DESC, id LIMIT 100", (dest, now)).fetchall()
            for r in rows:
                if selector and not selector_ok(json.loads(r["headers"]), selector):
                    continue
                if r["deliveries"] >= MAX_DELIVERIES:
                    c.execute("UPDATE messages SET state='dead', reason=COALESCE(reason, 'too many failed deliveries') WHERE id=?", (r["id"],))
                    continue
                c.execute("UPDATE messages SET state='inflight', deliveries=deliveries+1, visible_at=?, consumer=? WHERE id=?", (now + VISIBILITY, client, r["id"]))
                row = c.execute("SELECT * FROM messages WHERE id=?", (r["id"],)).fetchone()
                c.execute("COMMIT")
                return view(row)
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
    return None


@app.post("/receive")  # long poll: waits up to `wait` seconds for a message; 204 means none arrived
async def receive(request: Request):
    b = await request.json()
    dest = b.get("destination")
    if dest not in DEST:
        raise HTTPException(404, f"No such destination: {dest}")
    if not allowed(request, DEST[dest]["receive"]):
        raise HTTPException(403, f"'{client_of(request)}' may not receive from {dest}")
    deadline = time.time() + min(float(b.get("wait", 0)), 25)
    while True:
        try:
            if await request.is_disconnected():  # the receiver went away while waiting: do not hand its message to nobody
                return Response(status_code=204)
        except Exception:  # noqa: BLE001
            pass
        msg = claim(dest, b.get("selector", ""), client_of(request))
        if msg:
            return msg
        if time.time() >= deadline:
            return Response(status_code=204)
        await asyncio.sleep(0.2)


def settle(request, mid):
    with closing(conn()) as c:
        r = c.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
    if r is None or r["state"] != "inflight":
        raise HTTPException(409, "That message is not waiting for an acknowledgement (it may already have been settled or offered again)")
    if r["consumer"] != client_of(request):
        raise HTTPException(403, "Only the receiver of a message can acknowledge it")
    return r


@app.post("/ack")  # the consumer finished: the message is done
async def ack(request: Request):
    mid = (await request.json()).get("id")
    settle(request, mid)
    with closing(conn()) as c:
        c.execute("UPDATE messages SET state='done' WHERE id=?", (mid,))
    return {"ok": True}


@app.post("/nack")  # the consumer could not cope: try again later, or give up (dead=true goes straight to the dead-letter list)
async def nack(request: Request):
    b = await request.json()
    r = settle(request, b.get("id"))
    dead = bool(b.get("dead")) or r["deliveries"] >= MAX_DELIVERIES
    with closing(conn()) as c:
        if dead:
            c.execute("UPDATE messages SET state='dead', reason=? WHERE id=?", (b.get("reason") or "too many failed deliveries", r["id"]))
        else:
            c.execute("UPDATE messages SET state='ready', available_at=?, reason=? WHERE id=?",
                      (time.time() + float(b.get("delay", RETRY_DELAY)), b.get("reason"), r["id"]))
    return {"ok": True, "dead": dead}


def admin_only(request):
    if client_of(request) not in ADMIN:
        raise HTTPException(403, "Only the gateway may use the admin calls")


def destinations():
    with closing(conn()) as c:
        counts = c.execute("SELECT destination, state, COUNT(*) n, MIN(created) oldest FROM messages GROUP BY destination, state").fetchall()
    out = {d: {"id": d, "destination": d, "kind": r["kind"], "ready": 0, "inflight": 0, "dead": 0, "done": 0,
               "who_sends": ", ".join(sorted(r["send"])), "who_receives": ", ".join(sorted(r["receive"])), "purpose": r["doc"]}
           for d, r in DEST.items()}
    for r in counts:
        if r["destination"] in out:
            out[r["destination"]][r["state"]] = r["n"]
    return list(out.values())


@app.get("/admin/destinations")
async def admin_destinations(request: Request):
    admin_only(request)
    return destinations()


@app.get("/admin/messages")  # look inside a destination, for example its dead letters
async def admin_messages(request: Request, destination: str, state: str = "dead", limit: int = 50):
    admin_only(request)
    with closing(conn()) as c:
        rows = c.execute("SELECT * FROM messages WHERE destination=? AND state=? ORDER BY id DESC LIMIT ?", (destination, state, limit)).fetchall()
    return [view(r) for r in rows]


@app.post("/admin/retry")  # put every dead letter of a destination back in line
async def admin_retry(request: Request):
    admin_only(request)
    dest = (await request.json()).get("destination")
    if dest not in DEST:
        raise HTTPException(404, f"No such destination: {dest}")
    with closing(conn()) as c:
        n = c.execute("UPDATE messages SET state='ready', deliveries=0, available_at=?, reason=NULL WHERE destination=? AND state='dead'", (time.time(), dest)).rowcount
    return {"retried": n}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/")  # home page of the broker (styled for browsers)
def overview():
    return {"service": "broker", "port": int(cfg.get("port")), "database": cfg.get("db"), "destinations": destinations(),
            "settings": {k: v for k, v in S.attrib.items()}}


if __name__ == "__main__":
    uvicorn.run(app, port=int(cfg.get("port")), log_level="warning", timeout_graceful_shutdown=2)
