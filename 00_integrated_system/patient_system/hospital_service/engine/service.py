"""Generic XML-driven service engine (v3: knows who is acting, and speaks to the message broker). Vendored into every service folder: do not edit it there (see integration/engine_src).
Run:  python engine/service.py service.xml
Tables, endpoints and peer services are declared in the XML; this file only executes them."""
import asyncio, hmac, importlib.util, json, os, re, sqlite3, sys
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager, closing
import httpx, uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from messaging import Broker, Permanent, consume
from pages import nice


KEY = os.environ.get("PPS_SERVICE_KEY") or sys.exit("PPS_SERVICE_KEY is not set (python run.py sets it).")


HTTP = httpx.AsyncClient(timeout=5)  # one client for calls to peers: connections are reused


def load_hooks(xml_path):
    """Optional business rules in hooks.py next to service.xml: HOOKS = {"name": function(row, run, root)}."""
    path = os.path.join(os.path.dirname(os.path.abspath(xml_path)), "hooks.py")
    if not os.path.exists(path):
        return {}
    spec = importlib.util.spec_from_file_location("service_hooks", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, "HOOKS", {})


def matches(cond, row):  # "field=value,field!=value": every condition must hold ("field!=" means: not empty)
    for c in filter(None, (c.strip() for c in (cond or "").split(","))):
        k, _, v = c.partition("=")
        if (str(row.get(k[:-1], "")) == v) if k.endswith("!") else (str(row.get(k, "")) != v):
            return False
    return True


def call_hook(fn, row, run, root, actor, action):
    """Hooks may take (row, run, root) or (row, run, root, actor, action); actor is {"user", "role"} or None."""
    return fn(row, run, root, actor, action) if fn.__code__.co_argcount >= 5 else fn(row, run, root)


def create_app(xml_path):
    root = ET.parse(xml_path).getroot()
    hooks = load_hooks(xml_path)
    for e in root.findall("endpoint"):  # fail early and clearly if service.xml names a hook that hooks.py lacks
        for h in filter(None, e.get("hook", "").split(",")):
            if h.strip() not in hooks:
                sys.exit("%s uses hook '%s' but hooks.py has no such function" % (e.get("path"), h.strip()))
    data = os.environ.get("PPS_DATA") or os.path.dirname(os.path.abspath(xml_path))
    os.makedirs(data, exist_ok=True)
    db_file = os.path.join(data, root.get("db"))
    peers = {p.get("name"): p.get("url") for p in root.findall("peer")}
    cols = {}  # table -> {field: default}

    def run(sql, args=()):
        with closing(sqlite3.connect(db_file, timeout=10)) as c:
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA synchronous=NORMAL")  # with WAL a commit does not wait for the disk twice
            with c:
                cur = c.execute(sql, args)
                return [dict(r) for r in cur.fetchall()], cur.lastrowid

    with closing(sqlite3.connect(db_file)) as c:
        c.execute("PRAGMA journal_mode=WAL")
    for t in root.findall("table"):
        name = t.get("name")
        cols[name] = dict(f.partition("=")[::2] for f in t.get("fields").split(","))
        unique = f", UNIQUE({t.get('unique')})" if t.get("unique") else ""
        run(f"CREATE TABLE IF NOT EXISTS {name} (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            + ", ".join(f"{k} TEXT" for k in cols[name])
            + ", created TEXT DEFAULT CURRENT_TIMESTAMP" + unique + ")")

    msg = root.find("messaging")
    broker = Broker(msg.get("broker"), msg.get("client"), KEY) if msg is not None else None
    sends = msg.findall("send") if msg is not None else []
    if msg is not None:  # the outbox keeps messages safe until the broker has them; _processed makes repeats harmless
        run("CREATE TABLE IF NOT EXISTS _outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP)")
        run("CREATE TABLE IF NOT EXISTS _processed (message_id INTEGER PRIMARY KEY, at TEXT DEFAULT CURRENT_TIMESTAMP)")
    by_tag = {f"{e.get('method')} {e.get('path')}": e for e in root.findall("endpoint")}
    for c in (msg.findall("consume") if msg is not None else []):
        if c.get("endpoint") not in by_tag:
            sys.exit(f"<consume queue='{c.get('queue')}'> names '{c.get('endpoint')}' which is not an endpoint in service.xml")
    flush = {"event": None}

    def one(table, rid):
        rows, _ = run(f"SELECT * FROM {table} WHERE id=?", (rid,))
        if not rows:
            raise HTTPException(404, f"{table} {rid} not found")
        return rows[0]

    async def call(peer, method, path, body, actor=None):
        who = {"x-user": actor["user"], "x-role": actor["role"]} if actor else {}
        r = await HTTP.request(method, peers[peer] + path, json=body, headers={"accept": "application/json", "x-service-key": KEY, **who})
        if r.is_error:
            raise HTTPException(r.status_code, r.json().get("detail", r.text))
        return r.json()

    def queue_send(destination, body, headers=None, correlation_id=None, reply_to=None):
        spec = {"destination": destination, "body": body, "headers": headers or {}, "correlation_id": correlation_id, "reply_to": reply_to}
        run("INSERT INTO _outbox (payload) VALUES (?)", (json.dumps(spec),))
        if flush["event"]:
            flush["event"].set()

    def emit(e, result):  # <send after="POST /x" to="queue-or-topic" fields="a,b" set="k=v" when="f=v" type="Name" .../>
        if not isinstance(result, dict):
            return
        tag = f"{e.get('method')} {e.get('path')}"
        for s in sends:
            if s.get("after") == tag and matches(s.get("when"), result):
                fields = [f for f in s.get("fields", "").split(",") if f] or list(result)
                payload = {f: result.get(f) for f in fields}
                payload.update(kv.split("=", 1) for kv in s.get("set", "").split(",") if kv)
                corr = str(result.get(s.get("correlation"))) if s.get("correlation") else None
                queue_send(s.get("to"), payload, {"type": s.get("type")} if s.get("type") else {}, corr, s.get("reply_to"))

    async def relay():  # outbox -> broker, in order; if the broker is down the messages simply wait here
        while True:
            try:
                await asyncio.wait_for(flush["event"].wait(), 1.0)
            except asyncio.TimeoutError:
                pass
            flush["event"].clear()
            for r in run("SELECT id, payload FROM _outbox ORDER BY id LIMIT 100")[0]:
                spec = json.loads(r["payload"])
                try:
                    await broker.send(spec["destination"], spec["body"], spec["headers"], spec["correlation_id"], spec["reply_to"])
                except httpx.HTTPStatusError as e:
                    if e.response.status_code < 500:  # refused for good (unknown destination, not allowed): do not block the line
                        print(f"[{msg.get('client')}] broker refused a message to {spec['destination']}: {e.response.text[:120]}", file=sys.stderr, flush=True)
                    else:
                        break
                except httpx.HTTPError:
                    break
                run("DELETE FROM _outbox WHERE id=?", (r["id"],))

    async def on_message(e, id_field, m):
        if run("SELECT 1 FROM _processed WHERE message_id=?", (m["id"],))[0]:
            return  # delivered twice: already done
        body = m["body"] if isinstance(m["body"], dict) else {}
        param = re.search(r"\{(\w+)\}", e.get("path"))
        rid = m.get("correlation_id") if id_field == "correlation_id" else (body.get(id_field or param.group(1)) if param else None)
        h = m.get("headers") or {}
        actor = {"user": h.get("user", ""), "role": h.get("role", "")} if h.get("user") else None  # who the gateway acted for
        try:
            await execute(e, body, rid, {}, actor)
        except HTTPException as ex:
            if ex.status_code < 500:
                raise Permanent(f"{ex.status_code}: {ex.detail}")
            raise
        except sqlite3.IntegrityError:
            raise Permanent("409: record already exists")
        run("INSERT OR IGNORE INTO _processed (message_id) VALUES (?)", (m["id"],))

    @asynccontextmanager
    async def lifespan(app):
        tasks = []
        if broker:
            flush["event"] = asyncio.Event()
            tasks.append(asyncio.create_task(relay()))
            for c in msg.findall("consume"):
                tasks.append(asyncio.create_task(consume(
                    broker, c.get("queue"), lambda m, e=by_tag[c.get("endpoint")], i=c.get("id"): on_message(e, i, m), c.get("selector", ""))))
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(title=root.get("name") + " service", lifespan=lifespan)
    app.state.port = int(root.get("port"))

    @app.middleware("http")  # only the gateway (and sibling services) may call a service; people use the portal
    async def guard(request, call_next):
        if not hmac.compare_digest(request.headers.get("x-service-key", ""), KEY):
            return JSONResponse({"detail": "Services accept requests from the gateway only. Use the portal."}, 401)
        return await call_next(request)

    app.middleware("http")(nice)  # added last = outermost, so browsers get a styled page even for the 401

    @app.exception_handler(httpx.HTTPError)
    async def peer_down(request, exc):
        return JSONResponse({"detail": "peer service unavailable"}, 503)

    @app.exception_handler(sqlite3.IntegrityError)
    async def duplicate(request, exc):
        return JSONResponse({"detail": "record already exists"}, 409)

    WHAT = {"list": "List records", "get": "Get one record", "insert": "Create a record", "update": "Update a record"}

    @app.get("/health")  # a light "are you there?" for the gateway's status lights
    def health():
        return {"ok": True}

    @app.get("/")  # home page of this organisation's service
    def overview():
        eps = root.findall("endpoint")
        return {
            "service": root.get("name"), "port": app.state.port, "database": root.get("db"),
            "tables": [{"table": t, "records": run(f"SELECT COUNT(*) AS n FROM {t}")[0][0]["n"],
                        "open": next((e.get("path") for e in eps if e.get("table") == t and e.get("action") == "list"), "")}
                       for t in cols],
            "endpoints": [{"method": e.get("method"), "path": e.get("path"),
                           "does": WHAT.get(e.get("action")) or "Send to " + e.get("peer", "a peer service")} for e in eps],
            **({"messaging": {
                "receives": [{"queue": c.get("queue"), "handled_by": c.get("endpoint")} for c in msg.findall("consume")],
                "sends": [{"after": s.get("after"), "to": s.get("to"), "type": s.get("type") or "", "only_when": s.get("when") or ""} for s in sends],
                "waiting_in_outbox": run("SELECT COUNT(*) AS n FROM _outbox")[0][0]["n"]}} if msg is not None else {}),
        }

    async def execute(e, body, rid, query, actor=None):
        """Run one endpoint, whether the request came over HTTP or from a message queue, then announce what happened."""
        result = await perform(e, body, rid, query, actor)
        emit(e, result)
        return result

    async def perform(e, body, rid, query, actor):
        table, action = e.get("table"), e.get("action")
        stamps = [c.strip() for c in e.get("stamp", "").split(",") if c.strip()]  # columns that record who did this
        hook_names = [h.strip() for h in e.get("hook", "").split(",") if h.strip()]

        if action == "list":      # GET /things?field=value
            f = {k: v for k, v in query.items() if k in cols[table]}
            for rule in filter(None, e.get("scope", "").split(",")):  # scope="role:column": that role only sees its own rows
                role, _, col = rule.partition(":")
                if actor and actor["role"] == role:
                    f[col] = actor["user"]
            where = " WHERE " + " AND ".join(f"{k}=?" for k in f) if f else ""
            return run(f"SELECT * FROM {table}{where}", tuple(f.values()))[0]

        if action == "get":       # GET /things/{id}
            return one(table, rid)

        if action == "insert":    # POST /things
            row = {k: body.get(k, d) for k, d in cols[table].items()}
            if actor:
                for col in stamps:
                    row[col] = actor["user"]
            for h in hook_names:
                call_hook(hooks[h], row, run, root, actor, "insert")
            _, new_id = run(f"INSERT INTO {table} ({','.join(row)}) "
                            f"VALUES ({','.join('?' * len(row))})", tuple(row.values()))
            return one(table, new_id)

        if action == "update":    # PUT /things/{id}   (+ fixed values from set="a=b")
            existing = one(table, rid)
            new = {k: v for k, v in body.items() if k in cols[table]}
            new.update(kv.split("=", 1) for kv in e.get("set", "").split(",") if kv)
            if actor:
                for col in stamps:
                    new[col] = actor["user"]
            merged = {**existing, **new}
            for h in hook_names:  # a hook may refuse (HTTPException) or adjust the values
                call_hook(hooks[h], merged, run, root, actor, "update")
            changed = {k: merged[k] for k in cols[table] if merged.get(k) != existing.get(k)}
            if changed:
                run(f"UPDATE {table} SET {','.join(k + '=?' for k in changed)} WHERE id=?", (*changed.values(), rid))
            return one(table, rid)

        if action == "forward":   # send the request on to a peer, adding fields from our own DB
            for a in e.findall("attach"):
                body[a.get("field")] = one(a.get("table"), body.get(a.get("key")))[a.get("field")]
            return await call(e.get("peer"), "POST", e.get("path"), body, actor)

    def make(e):
        async def handle(request: Request):
            raw = await request.body()
            body = json.loads(raw) if raw else {}
            rid = next(iter(request.path_params.values()), None)
            who = request.headers.get("x-user")  # the gateway says who is acting (services trust only the gateway)
            actor = {"user": who, "role": request.headers.get("x-role", "")} if who else None
            return await execute(e, body, rid, dict(request.query_params), actor)

        return handle

    for e in root.findall("endpoint"):
        app.add_api_route(e.get("path"), make(e), methods=[e.get("method")])
    return app


if __name__ == "__main__":
    app = create_app(sys.argv[1])
    uvicorn.run(app, port=app.state.port, log_level="warning", timeout_graceful_shutdown=2)  # do not wait for idle kept-alive connections
