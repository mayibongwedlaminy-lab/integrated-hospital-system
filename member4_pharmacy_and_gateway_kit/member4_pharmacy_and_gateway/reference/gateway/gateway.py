"""API gateway: JWT login with lockout, role checks, routing, audit log, notifications, history, discharge PDF.
Routes, roles, hashed accounts, upstreams and history sources all live in gateway.xml."""
import asyncio, hashlib, hmac, json, os, re, secrets, sqlite3, sys, time
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager, closing
import httpx, jwt, uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "engine"))
from messaging import Broker, consume  # noqa: E402
from pages import nice  # noqa: E402  (browser-friendly pages)
from report import discharge_pdf  # noqa: E402

cfg = ET.parse(os.path.join(HERE, "gateway.xml")).getroot()
SEC = cfg.find("security")
MAX_TRIES, LOCK_SECS, TOKEN_SECS = int(SEC.get("max_attempts")), int(SEC.get("lock_minutes")) * 60, int(SEC.get("token_minutes")) * 60
DATA = os.environ.get("PPS_DATA") or HERE
os.makedirs(DATA, exist_ok=True)
DB = os.path.join(DATA, "gateway.db")
SERVICE_KEY = os.environ.get("PPS_SERVICE_KEY") or sys.exit("PPS_SERVICE_KEY is not set (python run.py sets it).")
UP = {u.get("name"): u.get("url") for u in cfg.findall("upstream")}
ROUTES = [(r.get("method"), re.compile(re.sub(r"\{\w+\}", "[^/]+", r.get("path"))),
           r.get("upstream"), r.get("roles").split(","), r.get("queue")) for r in cfg.findall("route")]
HISTORY = cfg.find("history")
NOTIFY = cfg.findall("notify")  # <notify event="LabResultReady" to="doctor" text="...">: who hears about which event
broker = Broker(UP["broker"], "gateway", SERVICE_KEY)
MODULES = json.loads(os.environ.get("PPS_MODULE_DIRS") or "{}")  # set by the project's run.py; defaults to sibling folders


def module_dir(name):
    return MODULES.get(name) or os.path.join(HERE, "..", name)


DOCS = {d.get("name"): (os.path.join(module_dir(d.get("module")), d.get("file")), d.get("title")) for d in cfg.findall("doc")}
XSL = '<?xml-stylesheet type="text/xsl" href="/ui/xml.xsl"?>\n'
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; object-src 'none'; "
       "base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


def sql(q, args=()):
    with closing(sqlite3.connect(DB, timeout=10)) as c, c:
        c.execute("PRAGMA synchronous=NORMAL")  # with WAL (set below) a commit no longer waits for the disk twice
        return c.execute(q, args).fetchall()


def hash_pw(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 100_000).hex()


with closing(sqlite3.connect(DB)) as _c:
    _c.execute("PRAGMA journal_mode=WAL")
sql("CREATE TABLE IF NOT EXISTS users (name TEXT PRIMARY KEY, salt TEXT, hash TEXT, role TEXT, full_name TEXT DEFAULT '', active INTEGER DEFAULT 1, source TEXT DEFAULT 'xml')")
sql("CREATE TABLE IF NOT EXISTS audit (time TEXT, user TEXT, role TEXT, method TEXT, path TEXT, status INT)")
sql("CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, to_role TEXT, to_user TEXT, text TEXT)")
for _table, _col, _decl in [("users", "full_name", "TEXT DEFAULT ''"), ("users", "active", "INTEGER DEFAULT 1"), ("users", "source", "TEXT DEFAULT 'xml'"),
                            ("users", "must_change", "INTEGER DEFAULT 0"),
                            ("notifications", "to_user", "TEXT")]:  # databases made by an older version get the new columns
    if _col not in {r[1] for r in sql(f"PRAGMA table_info({_table})")}:
        sql(f"ALTER TABLE {_table} ADD COLUMN {_col} {_decl}")
sql("CREATE TABLE IF NOT EXISTS seen (user TEXT PRIMARY KEY, last_id INT)")
sql("CREATE TABLE IF NOT EXISTS attempts (user TEXT, time REAL)")
sql("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
sql("INSERT OR IGNORE INTO settings VALUES ('jwt_secret', ?)", (secrets.token_hex(32),))
SECRET = os.environ.get("PPS_SECRET") or sql("SELECT value FROM settings WHERE key='jwt_secret'")[0][0]
accounts_xml = cfg.findall("user")  # the XML is the source of truth for accounts
for u in accounts_xml:  # the starting account(s) in the XML are created once, on the very first start; after that the database is the truth
    sql("INSERT INTO users (name, salt, hash, role, full_name, active, source, must_change) VALUES (?,?,?,?,?,1,'xml',?) ON CONFLICT(name) DO NOTHING",
        (u.get("name"), u.get("salt"), u.get("hash"), u.get("role"), u.get("full_name", ""), 1 if u.get("must_change") == "yes" else 0))
STAFF = {r.get("role"): r for r in cfg.findall("staff-role")}  # which organisation holds each kind of staff member


def who(request):
    try:
        claims = jwt.decode(request.headers.get("authorization", "")[7:], SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Login required")
    row = sql("SELECT active, full_name FROM users WHERE name=?", (claims["sub"],))  # a deactivated account stops working at once, not when its token expires
    if not row or not row[0][0]:
        raise HTTPException(401, "This account is not active")
    claims["name"] = row[0][1] or claims["sub"]
    return claims


def audit_raw(user, role, method, path, status):  # FR11
    sql("INSERT INTO audit VALUES (datetime('now'),?,?,?,?,?)", (user, role, method, path, status))


def audit(user, request, status):
    audit_raw(user["sub"], user["role"], request.method, request.url.path, status)


def notify_event(kind, row):
    """Store a notification for every <notify event="..."> rule that matches this event."""
    for n in NOTIFY:
        if n.get("event") == kind and (not n.get("if") or row.get(n.get("if"))):
            text = re.sub(r"\{(\w+)\}", lambda k: str(row.get(k[1], "")), n.get("text"))
            person = row.get(n.get("user")) if n.get("user") else None  # user="doctor": only the doctor named in the event hears it
            sql("INSERT INTO notifications (time, to_role, to_user, text) VALUES (datetime('now'), ?, ?, ?)", (n.get("to"), person or None, text))


async def on_event(m):  # a message from the broker's "events" topic
    notify_event(m["headers"].get("type", ""), m["body"] if isinstance(m["body"], dict) else {})


HTTP = httpx.AsyncClient(timeout=5, limits=httpx.Limits(max_keepalive_connections=20))  # one client: connections are reused, not rebuilt per request


async def ask(method, url, body=None, user=None):
    who_ = {"x-user": user["sub"], "x-role": user["role"]} if user else {}  # the services trust the gateway about who is acting
    try:
        return await HTTP.request(method, url, content=body, headers={
            "content-type": "application/json", "accept": "application/json", "x-service-key": SERVICE_KEY, **who_})
    except httpx.HTTPError:
        return None


async def gather(pid, user=None):  # one record per organisation, asked at the same time; a service that is down becomes "unavailable"
    sources = HISTORY.findall("source")
    answers = await asyncio.gather(*[ask("GET", UP[s.get("upstream")] + s.get("path").format(id=pid), user=user) for s in sources])
    return {s.get("name"): r.json() if r is not None and r.is_success else "unavailable" for s, r in zip(sources, answers)}


@asynccontextmanager
async def lifespan(app):  # listen to the events topic for as long as the gateway runs
    task = asyncio.create_task(consume(broker, "events:gateway-notifications", on_event))
    yield
    task.cancel()
    await HTTP.aclose()


app = FastAPI(title="API Gateway", lifespan=lifespan)
app.middleware("http")(nice)


@app.middleware("http")  # outermost: safe headers on everything, a strict content policy on the portal
async def secure(request, call_next):
    resp = await call_next(request)
    resp.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "same-origin"})
    if not request.url.path.startswith("/ui/"):
        resp.headers["Cache-Control"] = "no-store"
    elif resp.headers.get("content-type", "").startswith("text/html"):
        resp.headers["Content-Security-Policy"] = CSP
    return resp


app.mount("/ui", StaticFiles(directory=module_dir("client"), html=True, check_dir=False), name="ui")


@app.get("/")
def home():
    return RedirectResponse("/ui/")


@app.post("/auth/login")  # FR1, with lockout after repeated failures
async def login(request: Request):
    try:
        b = await request.json()
    except ValueError:
        raise HTTPException(422, "Send a username and a password")
    name, pw = str(b.get("username") or ""), str(b.get("password") or "")
    if sql("SELECT COUNT(*) FROM attempts WHERE user=? AND time>?", (name, time.time() - LOCK_SECS))[0][0] >= MAX_TRIES:
        audit_raw(name, "-", "POST", "/auth/login", 429)
        raise HTTPException(429, f"Too many failed attempts. Try again in {LOCK_SECS // 60} minutes.")
    rows = sql("SELECT salt, hash, role, full_name, must_change FROM users WHERE name=? AND active=1", (name,))
    salt, good = (rows[0][0], rows[0][1]) if rows else ("00" * 8, "")
    if not (hmac.compare_digest(good, hash_pw(pw, salt)) and rows):  # same work and same message for unknown users
        sql("INSERT INTO attempts VALUES (?, ?)", (name, time.time()))
        audit_raw(name, "-", "POST", "/auth/login", 401)
        raise HTTPException(401, "Wrong username or password")
    sql("DELETE FROM attempts WHERE user=?", (name,))
    audit_raw(name, rows[0][2], "POST", "/auth/login", 200)
    token = jwt.encode({"sub": name, "role": rows[0][2], "exp": int(time.time()) + TOKEN_SECS}, SECRET, "HS256")
    return {"token": token, "role": rows[0][2], "username": name, "name": rows[0][3] or name, "must_change": bool(rows[0][4])}


@app.get("/api/status")  # which organisation services are online (drives the status lights)
async def status(request: Request):
    who(request)
    answers = await asyncio.gather(*[ask("GET", url + "/health") for url in UP.values()])  # all at once, and a light call
    return {name: r is not None and r.is_success for name, r in zip(UP, answers)}


def history_only(request):
    user = who(request)
    if user["role"] not in HISTORY.get("roles").split(","):
        audit(user, request, 403)
        raise HTTPException(403, "Role not allowed")
    return user


@app.get("/api/patients/{pid}/full-history")  # FR10
async def full_history(pid: str, request: Request):
    user = history_only(request)
    out = await gather(pid, user)
    audit(user, request, 200)
    return out


@app.get("/api/cases/{cid}/discharge.pdf")  # discharge summary for one case
async def discharge(cid: int, request: Request):
    user = history_only(request)
    r = await ask("GET", UP["hospital"] + f"/consultations/{cid}", user=user)
    if r is None or r.is_error:
        audit(user, request, 503 if r is None else r.status_code)
        raise HTTPException(503 if r is None else r.status_code, "hospital service unavailable" if r is None else "Case not found")
    case = r.json()
    pdf = discharge_pdf(case, await gather(case["patient_id"], user), user["sub"])
    audit(user, request, 200)
    return Response(pdf, media_type="application/pdf", headers={"content-disposition": f'attachment; filename="discharge-case-{cid}.pdf"'})


def admin_only(request):
    user = who(request)
    if user["role"] != "administrator":
        audit(user, request, 403)
        raise HTTPException(403, "Role not allowed")
    return user


@app.get("/notifications")  # the bell: newest 30 for the caller's role; unread = newer than what they last opened
async def notifications(request: Request):
    user = who(request)
    seen = sql("SELECT last_id FROM seen WHERE user=?", (user["sub"],))
    last = seen[0][0] if seen else 0
    rows = sql("SELECT id, time, text FROM notifications WHERE to_role=? AND (to_user IS NULL OR to_user=?) ORDER BY id DESC LIMIT 30", (user["role"], user["sub"]))
    return [{"id": i, "time": t, "text": x, "unread": i > last} for i, t, x in rows]


@app.post("/notifications/read")
async def notifications_read(request: Request):
    user = who(request)
    top = sql("SELECT COALESCE(MAX(id), 0) FROM notifications WHERE to_role=? AND (to_user IS NULL OR to_user=?)", (user["role"], user["sub"]))[0][0]
    sql("INSERT INTO seen VALUES (?, ?) ON CONFLICT(user) DO UPDATE SET last_id=excluded.last_id", (user["sub"], top))
    return {"ok": True}


@app.get("/api/messaging")  # the broker's queues, for the administrator
async def messaging_overview(request: Request):
    admin_only(request)
    try:
        return await broker.admin("/admin/destinations")
    except httpx.HTTPError:
        raise HTTPException(503, "broker service unavailable")


@app.post("/api/messaging/{destination}/retry")  # put a destination's dead letters back in line
async def messaging_retry(destination: str, request: Request):
    admin_only(request)
    try:
        done = await broker.admin("/admin/retry", {"destination": destination})
    except httpx.HTTPError:
        raise HTTPException(503, "broker service unavailable")
    audit(who(request), request, 200)
    return {"destination": destination, **done}


async def save_profile(rcfg, username, payload, admin):
    """Create or update the person's record in their organisation's own service."""
    base = UP[rcfg.get("upstream")] + rcfg.get("path")
    found = await ask("GET", f"{base}?username={username}", user=admin)
    if found is None or not found.is_success:
        return found
    rows = found.json()
    if rows:
        return await ask("PUT", f"{base}/{rows[0]['id']}", json.dumps(payload), admin)
    return await ask("POST", base, json.dumps(payload), admin)


async def save_staff(request, username=None):
    """Create a staff account (and the person's record at their organisation), or change an existing one."""
    admin = admin_only(request)
    b = await request.json()
    uname = (username or str(b.get("username", ""))).strip()
    existing = sql("SELECT role, full_name FROM users WHERE name=?", (uname,))
    role = existing[0][0] if existing else str(b.get("role", ""))
    rcfg = STAFF.get(role)
    if rcfg is None:
        raise HTTPException(422, "Choose a role: " + ", ".join(STAFF))
    if not re.fullmatch(r"[a-z0-9_.-]{3,30}", uname):
        raise HTTPException(422, "The username is 3 to 30 lowercase letters, digits, dots, dashes or underscores.")
    if existing and b.get("role") and b["role"] != role:
        raise HTTPException(409, f"'{uname}' is already a {role}.")
    full = str(b.get("full_name") or (existing[0][1] if existing else "")).strip()
    if not full:
        raise HTTPException(422, "Give the person's full name.")
    pw, creating = str(b.get("password") or ""), not existing
    if (creating or pw) and len(pw) < 8:
        raise HTTPException(422, "The password must be at least 8 characters.")
    active = {"yes": 1, "no": 0}.get(str(b.get("active", "")))
    if uname == admin["sub"] and active == 0:
        raise HTTPException(409, "You cannot deactivate your own account.")
    payload = {"username": uname, "full_name": full, "role": role,
               **{f: b[f] for f in (rcfg.get("fields") or "").split(",") if f and f in b}}
    if active is not None:
        payload["active"] = "yes" if active else "no"

    async def profile():
        if not rcfg.get("upstream"):
            return None
        r = await save_profile(rcfg, uname, payload, admin)
        if r is None or r.is_error:
            raise HTTPException(503 if r is None else r.status_code, "The organisation's service is not answering, so nothing was saved."
                                if r is None else r.json().get("detail", "The organisation's service refused it."))

    if creating:
        salt = secrets.token_hex(8)
        sql("INSERT INTO users (name, salt, hash, role, full_name, active, source, must_change) VALUES (?,?,?,?,?,1,'admin',1)", (uname, salt, hash_pw(pw, salt), role, full))
        try:
            await profile()
        except HTTPException:
            sql("DELETE FROM users WHERE name=?", (uname,))  # never leave an account without its record
            raise
    else:
        await profile()
        sql("UPDATE users SET full_name=? WHERE name=?", (full, uname))
        if active is not None:
            sql("UPDATE users SET active=? WHERE name=?", (active, uname))
        if pw:
            salt = secrets.token_hex(8)
            sql("UPDATE users SET salt=?, hash=?, must_change=? WHERE name=?", (salt, hash_pw(pw, salt), 0 if uname == admin["sub"] else 1, uname))
    audit(admin, request, 200)
    return {"id": uname, "username": uname, "full_name": full, "role": role, "created": creating}


@app.post("/api/staff")
async def staff_add(request: Request):
    return await save_staff(request)


@app.put("/api/staff/{username}")
async def staff_change(username: str, request: Request):
    return await save_staff(request, username)


@app.post("/api/password")  # anyone changes their own password
async def change_password(request: Request):
    user = who(request)
    b = await request.json()
    row = sql("SELECT salt, hash FROM users WHERE name=?", (user["sub"],))[0]
    if not hmac.compare_digest(row[1], hash_pw(str(b.get("current_password") or ""), row[0])):
        audit(user, request, 401)
        raise HTTPException(401, "The current password is not right.")
    new = str(b.get("new_password") or "")
    if len(new) < 8:
        raise HTTPException(422, "The new password must be at least 8 characters.")
    if new == b.get("current_password"):
        raise HTTPException(422, "Choose a password different from the current one.")
    salt = secrets.token_hex(8)
    sql("UPDATE users SET salt=?, hash=?, must_change=0 WHERE name=?", (salt, hash_pw(new, salt), user["sub"]))
    audit(user, request, 200)
    return {"ok": True}


@app.get("/api/people")  # names for the portal: a username becomes "Dr. Sipho Dlamini" (anyone signed in may ask)
async def people(request: Request):
    who(request)
    return [{"id": n, "username": n, "full_name": f or n, "role": r} for n, f, r in sql("SELECT name, full_name, role FROM users ORDER BY full_name")]


@app.get("/api/staff")  # every account with their record from their organisation
async def staff_list(request: Request):
    admin = admin_only(request)
    rows = {n: {"id": n, "username": n, "full_name": f or n, "role": r, "active": "yes" if a else "no", "source": src,
                "specialty": "", "schedule": "", "note": ""}
            for n, r, f, a, src in sql("SELECT name, role, full_name, active, source FROM users ORDER BY role, name")}
    where = sorted({(c.get("upstream"), c.get("path")) for c in STAFF.values() if c.get("upstream")})
    answers = await asyncio.gather(*[ask("GET", UP[u] + p, user=admin) for u, p in where])
    offline = []
    for (u, _), r in zip(where, answers):
        if r is None or not r.is_success:
            offline.append(u)
            continue
        for prof in r.json():
            if prof["username"] in rows:
                row = rows[prof["username"]]
                row["specialty"] = prof.get("specialty", "")
                row["schedule"] = f"{prof['working_days']} {prof['start']}-{prof['end']}" if prof.get("working_days") else ""
                row["profile"] = "yes"
    for row in rows.values():
        if STAFF.get(row["role"]) is not None and STAFF[row["role"]].get("upstream") and "profile" not in row:
            up = STAFF[row["role"]].get("upstream")
            row["note"] = f"{up} service offline" if up in offline else "no record at the organisation yet"
        elif row["role"] == "doctor" and not row["schedule"]:
            row["note"] = "no working days and hours set: cannot be booked yet"
    return list(rows.values())


@app.get("/audit")  # FR11: the audit log, newest first
async def audit_log(request: Request):
    admin_only(request)
    cols = ("id", "time", "user", "role", "method", "path", "status")
    rows = sql("SELECT rowid, time, user, role, method, path, status FROM audit ORDER BY rowid DESC LIMIT 200")
    return [dict(zip(cols, r)) for r in rows]


@app.get("/users")
async def accounts(request: Request):
    admin_only(request)
    return [{"name": n, "role": r} for n, r in sql("SELECT name, role FROM users ORDER BY rowid")]


@app.get("/xml")  # index of the XML definitions, shown as a styled page
async def xml_index():
    return [{"definition": t, "view": f"/xml/{n}.xml"} for n, (_, t) in DOCS.items()]


@app.get("/xml/{name}.xml")  # the XML itself; the browser styles it with /ui/xml.xsl
async def xml_doc(name: str):
    if name not in DOCS:
        raise HTTPException(404, "No such definition")
    text = re.sub(r"<\?xml-stylesheet[^>]*\?>\s*", "", open(DOCS[name][0], encoding="utf-8").read())
    return Response(XSL + text, media_type="application/xml")


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT"])
async def proxy(request: Request):
    user, path = who(request), request.url.path
    for method, rx, upstream, roles, queue in ROUTES:
        if method == request.method and rx.fullmatch(path):
            if user["role"] not in roles:
                audit(user, request, 403)
                raise HTTPException(403, "Role not allowed")
            url = UP[upstream] + path + ("?" + request.url.query if request.url.query else "")
            raw = await request.body()
            r = await ask(method, url, raw, user)
            if r is None and queue and method in ("POST", "PUT"):  # store-and-forward: keep the request until the service is back
                try:
                    sent = await broker.send(queue, json.loads(raw or b"{}"), {"user": user["sub"], "role": user["role"], "method": method, "path": path})
                    audit(user, request, 202)
                    return JSONResponse({"queued": True, "message_id": sent["id"], "detail":
                                         f"The {upstream} service is offline. Your request is saved and will be delivered automatically when it is back."}, 202)
                except httpx.HTTPError:
                    pass  # the broker is down too: nothing safe to do but report it
            if r is None:  # service offline: only this route fails
                audit(user, request, 503)
                return JSONResponse({"detail": f"{upstream} service unavailable"}, 503)
            audit(user, request, r.status_code)
            return JSONResponse(r.json(), r.status_code)
    raise HTTPException(404, "No such route")


if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("PPS_HOST", "127.0.0.1"), port=int(cfg.get("port")), log_level="warning", timeout_graceful_shutdown=2)
