"""Browsers get a styled page; programs (and the portal's own fetch calls) still get JSON.
Used as middleware by the gateway and by every organisation service."""
import html, json, os
from datetime import datetime
from fastapi.responses import HTMLResponse

HERE = os.path.dirname(os.path.abspath(__file__))
CSS = open(os.path.join(HERE, "app.css"), encoding="utf-8").read()  # vendored copy of client/app.css
PORT = os.environ.get("PPS_PORTAL_PORT", "8000")  # where the portal lives, for the "Open the portal" links
SCRIPT = """
document.querySelectorAll('.tbl').forEach(box => {
  const body = box.querySelector('tbody'), rows = [...body.rows];
  box.querySelector('.filter').addEventListener('input', e => {
    const q = e.target.value.toLowerCase();
    rows.forEach(r => r.hidden = !r.textContent.toLowerCase().includes(q));
  });
  box.querySelectorAll('th').forEach((th, i) => {
    const sort = () => {
      const d = th.dataset.dir = th.dataset.dir === '1' ? '-1' : '1';
      [...rows].sort((a, b) => {
        const x = a.cells[i].textContent.trim(), y = b.cells[i].textContent.trim();
        return (x !== '' && y !== '' && !isNaN(x) && !isNaN(y) ? x - y : x.localeCompare(y)) * d;
      }).forEach(r => body.append(r));
    };
    th.onclick = sort; th.onkeydown = e => e.key === 'Enter' && sort();
  });
});
"""
EXTRA = """
.kv{display:grid;grid-template-columns:max-content 1fr;gap:.45rem 1.75rem;margin:0 0 1rem}
.kv dt{color:var(--muted);font-weight:600}.kv dd{margin:0}
.card h3{margin:1.25rem 0 .5rem;font-size:1rem}
.card{padding:1.25rem}.card .table-wrap{margin:0 -1.25rem}
.who{margin-left:auto}
.notice{margin:0 0 1rem}.notice p{margin:.35rem 0 0}
"""
TONE = {"pending": "amber", "open": "blue", "completed": "green", "reported": "green",
        "dispensed": "green", "closed": "green"}
ERRORS = {
    401: ("Log in to continue", "This address needs a login. Open the portal and log in with your role."),
    403: ("Not allowed for your role", "Your role cannot use this address. Log in with a different role in the portal."),
    404: ("Not found", "There is nothing at this address."),
    409: ("Already exists", "A record with these details is already stored."),
    422: ("Check the details", "Some details are missing or in the wrong format."),
    405: ("Not available here", "This address does not support that action."),
    429: ("Too many attempts", "Wait a few minutes before trying again."),
    503: ("Service offline", "The service behind this address is not running. The rest of the system keeps working."),
}
TITLES = {"/xml": "XML definitions", "/audit": "Audit log", "/users": "Accounts"}
esc = html.escape
label = lambda k: str(k).replace("_", " ").capitalize()


def cell(key, v):
    if key == "warning" and not v:
        return '<span class="badge green plain">Clear</span>'
    if key == "interaction" and not v:
        return '<span class="badge green plain">None found</span>'
    if v in ("", None):
        return '<span class="dim">–</span>'
    s = str(v)
    if key == "status":
        return f'<span class="badge {TONE.get(s, "blue")}">{esc(s)}</span>'
    if key == "warning":
        return f'<span class="badge red">{esc(s)}</span>'
    if key == "interaction":
        return f'<span class="badge amber">{esc(s)}</span>'
    if key == "allergies":
        return "".join(f'<span class="chip">{esc(a.strip())}</span>' for a in s.split(","))
    if key == "open":
        return f'<a href="{esc(s)}">View records</a>'
    if key == "view":
        return f'<a class="btn small" href="{esc(s)}">Open</a>'
    if key == "created":
        try:
            return esc(datetime.strptime(s, "%Y-%m-%d %H:%M:%S").strftime("%d %b, %H:%M"))
        except ValueError:
            pass
    return esc(s)


def table(rows):
    cols = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    head = "".join(f'<th tabindex="0" title="Click to sort">{esc(label(c))}</th>' for c in cols)
    body = "".join("<tr>" + "".join(f'<td data-label="{esc(label(c))}">{cell(c, r.get(c))}</td>' for c in cols) + "</tr>" for r in rows)
    return (f'<div class="tbl"><div class="toolbar"><input class="filter" type="search" placeholder="Search this table" '
            f'aria-label="Search this table"></div><div class="table-wrap"><table><thead><tr>{head}</tr></thead>'
            f'<tbody>{body}</tbody></table></div></div>')


def block(v):
    if isinstance(v, list):
        if not v:
            return '<div class="empty">Nothing here yet.</div>'
        if all(isinstance(r, dict) for r in v):
            return table(v)
        return "<ul>" + "".join(f"<li>{esc(str(x))}</li>" for x in v) + "</ul>"
    if isinstance(v, dict):
        simple = {k: x for k, x in v.items() if not isinstance(x, (list, dict))}
        out = '<dl class="kv">' + "".join(f"<dt>{esc(label(k))}</dt><dd>{cell(k, x)}</dd>" for k, x in simple.items()) + "</dl>" if simple else ""
        return out + "".join(f"<h3>{esc(label(k))}</h3>{block(x)}" for k, x in v.items() if isinstance(x, (list, dict)))
    return f"<p>{esc(str(v))}</p>"


def page(title, sub, body, base):
    portal = base + "/ui/"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title>
<style>{CSS}{EXTRA}</style></head><body>
<header class="nav"><a class="brand" href="{portal}"><span class="hex"></span><b>Patient Processing System</b></a>
<div class="who"><a class="btn ghost" href="{portal}">Open the portal</a></div></header>
<section class="hero small"><div class="wrap"><h1>{esc(title)}</h1><p>{esc(sub)}</p></div></section>
<div class="wrap pull"><section class="card">{body}</section></div>
<footer class="foot"><a href="{base}/xml">XML definitions</a><a href="{base}/docs">API documentation</a></footer>
<script>{SCRIPT}</script></body></html>"""


def render(request, data, status):
    base = f"{request.url.scheme}://{request.url.hostname}:{PORT}"
    portal = base + "/ui/"
    if status >= 400:
        title, hint = ERRORS.get(status, ("Something went wrong", ""))
        detail = data.get("detail", "") if isinstance(data, dict) else ""
        if isinstance(detail, list):
            detail = "; ".join(str(d.get("msg", d)) for d in detail)
        body = (f'<div class="notice down"><b>{esc(title)}</b><p>{esc(str(detail))}</p><p>{esc(hint)}</p></div>'
                f'<a class="btn primary" href="{portal}">Open the portal</a>')
        return page(f"{status}: {title}", request.url.path, body, base)
    if isinstance(data, dict) and "service" in data:
        return page(f"{str(data['service']).capitalize()} service", "Records are stored only by this organisation.", block(data), base)
    name = TITLES.get(request.url.path) or label(request.url.path.strip("/").replace("/", " ") or "Home")
    return page(name, request.url.path, block(data), base)


async def nice(request, call_next):
    resp = await call_next(request)
    # HTML is the default for anything a person might open; JSON only when a program explicitly asks for it
    if (request.method == "GET" and "application/json" not in request.headers.get("accept", "")
            and resp.headers.get("content-type", "").startswith("application/json")
            and not request.url.path.startswith(("/openapi.json", "/docs", "/redoc"))):
        raw = b"".join([c async for c in resp.body_iterator])
        return HTMLResponse(render(request, json.loads(raw), resp.status_code), resp.status_code)
    return resp
