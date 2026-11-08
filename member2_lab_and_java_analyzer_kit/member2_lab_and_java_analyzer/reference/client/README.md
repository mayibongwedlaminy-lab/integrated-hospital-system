# Client portal (served by the gateway at /ui/)

**You own:** everything people see in the browser: login, dashboards per role, forms, tables, the patient history and charts, dark mode, phone layout, accessibility.

## Your files
| File | What it holds |
|---|---|
| `portal.xml` | **the dashboards**: per role the tiles, charts, tabs and buttons; the forms; the history timeline; the vital-sign charts. Most changes are XML only. |
| `app.js` | the code that reads `portal.xml` and draws the portal |
| `app.css`, `xml.css`, `xml.xsl` | the stylesheet, the XML viewer styles and stylesheet |
| `index.html`, `theme.js` | the page and the colour-theme switch |

## What you rely on
- The routes the gateway offers to each role (`gateway/gateway.xml`, including its `<local>` endpoints). `python check.py` fails if a screen uses a route its role may not use.
- Field names in the services' answers (see `contracts/*.contract.xml`).
- The stylesheet is also copied into every service (for their styled pages): if you change `app.css`, tell the team lead to run `python integration/sync_modules.py`.

## Messaging in the portal
- The administrator's **Messaging** tab shows every queue (waiting, being handled, dead letters) and a **Retry dead letters** button.
- When a request is **queued** (the service was offline) the gateway answers `202` and the portal shows an amber message instead of a green one.

## How you work
1. `python run.py` (top folder): starts a complete backend from `reference/` and serves **your** `client/` folder. Edit, refresh the browser.
2. `python check.py` (static checks only for you), and `pytest integration/tests/test_ui.py` for the browser tests (needs `playwright install chromium`).
3. Send back **only `client/`**, zipped.

## Rules
- No inline scripts or event handlers: the gateway sends a strict content policy (script from the same site only).
- Keep it accessible: labels, keyboard use, contrast. Both themes. The team checked it with axe-core: no violations.

## Roles, people and the first run
- There are **no demo accounts**. The sign-in page tells a first-time visitor to sign in as `admin` and add staff under Administration. A person whose password someone else chose is asked to choose their own (the **Password** button changes it any time).
- **Only mine**: a panel with `mine="column"` can be narrowed to the signed-in person's own rows (the tick-box above the table). `{me}` in a tile's `where` means the signed-in person. Names (`{doctor_name}`) in success messages come from `/api/people`.
- Form fields can be pickers that read the system: `type="choice" source="/staff?role=doctor&amp;active=yes"` (doctors), a `specialty` picker from `/specialists`, and `type="days"` (working-day tick-boxes).
- **Doctors** treat (`Treat`), refer (`Refer`), prescribe, close, and mark themselves unavailable. **Receptionists** register patients and book. **Specialists** treat or recommend. The **administrator** adds and manages staff.

## Ideas to build
- A dashboard for a new role, or more tiles and charts per role (all XML).
- A language switch (English / siSwati) driven by an XML strings file.
- Printable layouts for lab results and prescriptions; an "offline" banner when the gateway is unreachable.
