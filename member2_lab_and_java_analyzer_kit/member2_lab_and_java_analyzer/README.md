# Patient Processing System (CSC411)

Four organisations (hospital, laboratory, specialist clinic, pharmacy) each keep their own data behind their own service. A gateway gives each person
one login, one portal and one audit trail. A **message broker** lets the organisations (and a **Java lab analyzer**) exchange messages reliably.
Start with `docs/INTEGRATION.md` (how and why) and `TEAM_GUIDE.md` (who builds what).

**Three programming languages, one agreement.** The organisations are not copies of one program: the **pharmacy is Node.js (Express)**, the
**laboratory is Java**, and the hospital, specialist clinic, gateway and broker are **Python (FastAPI)**. They work together only because each keeps
the same interface contract (`contracts/*.xml`): REST + JSON, a shared service key, "who is acting" headers, and messages through the broker.

**The system starts empty.** There is no demo data and no demo accounts: you create everything through the portal.

## What you need
| For | Install | Notes |
|---|---|---|
| Python services, gateway, broker, the launcher | **Python 3.10+** | `pip install -r requirements.txt` |
| Pharmacy service | **Node.js 22.13+** (with npm) | the first start runs `npm install` for you (needs internet once) |
| Laboratory service and the lab analyzer | **Java 11+** (a JRE is enough; no Maven or Gradle) | compiled automatically on the first start |

## Run it

    pip install -r requirements.txt
    python run.py
    open http://localhost:8000/ui/

The start-up list shows which language each module is written in. Set `PPS_ANALYZER=0` to leave the Java analyzer out.

## First sign-in, then everything else
1. Sign in as **`admin`** with the starting password **`admin123`**. You are asked to choose a new password straight away.
2. Under Administration press **Add staff member** and create the people who will use the system. Each person gets their own account and a starting password (they must replace it at their first sign-in):
   - **receptionists**: register patients and book appointments
   - **doctors**: give their **working days and hours**, so appointments can be booked against them
   - **specialists**: give each a **specialty** (ENT, Cardiology, ...); referrals go to the specialist of that specialty
   - **lab technicians** and **pharmacists**
   You can add as many people per role as you like.
3. Sign in as each person (the **Password** button changes your own password any time) and do the work:

| Who | What they do |
|---|---|
| Receptionist | **registers patients** (only receptionists can), books appointments, edits details |
| Doctor | sees their own appointments and consultations; **treats** (diagnosis and plan) or **refers**; requests lab tests; **prescribes**; closes the case; marks themselves unavailable |
| Specialist | sees only referrals assigned to them; **treats** the patient or **recommends** a treatment to the referring doctor |
| Lab technician | enters results (automated tests such as Blood glucose are run by the Java analyzer) |
| Pharmacist | dispenses; allergy and drug-interaction warnings are shown |
| Administrator | adds, edits, deactivates staff; audit log; message queues |

**Appointments** are booked against the doctors' availability: the doctor asked for if free, otherwise another doctor free at that time, otherwise the next free slot.
Try it: add two doctors, book the same time twice, and read the note on the second appointment.

### Docker

    docker compose up --build   # then open http://localhost:8000/ui/

Only the gateway's port 8000 is published. Databases live in the `pps-data` volume. The image holds Python, Node.js and a JDK, so all three languages run in
one container. **The Dockerfile and compose file have not been run** (no Docker where this was written); the same system was tested without Docker.

### Settings (environment variables)
PPS_DATA = folder for the databases . PPS_HOST = gateway address (0.0.0.0 in a container) . PPS_SECRET = fixed token-signing secret .
PPS_ANALYZER=0 = do not start the Java analyzer.

## The pieces
| Folder | What | Port |
|---|---|---|
| `hospital_service/` `specialist_service/` | organisations written in **Python** (FastAPI, shared XML-driven engine), own database and own staff, REST | 8001, 8003 |
| `lab_service/` | the laboratory, written in **Java** (JDK only), own data file, own staff, REST + broker | 8002 |
| `pharmacy_service/` | the pharmacy, written in **Node.js** (Express + SQLite), own database, own staff, REST + broker | 8004 |
| `broker/` | message broker: queues, topic, acknowledgement, redelivery, dead letters | 8005 |
| `analyzer/` | the laboratory's automated analyzer, **in Java**, joins through the broker | none |
| `gateway/` | sign-in, accounts, roles, routing, audit, notifications, history, PDF; keeps requests for offline services | 8000 |
| `client/` | the portal (dashboards per role, forms, charts, dark mode) | served at /ui/ |
| `contracts/` | the agreed interface of each module, and the checkers | |
| `integration/` | run, shared engine, tests, kit builder | |

## For the team
- `python check.py`: is my module ready to hand over? (checks the shared pieces, the portal against the gateway, and each of your modules against its contract; it starts its own empty system)
- `pytest`: the whole system (stop any running copy first; ports 8000 to 8005). Browser tests need `playwright install chromium`; the Java tests need Java; the pharmacy needs Node.js.
- `cd pharmacy_service && npm test`: the pharmacy's own unit tests (allergy and interaction rules).
- Kits for each member: `python integration/make_kits.py` (see TEAM_GUIDE.md).

## Security
- Accounts are salted PBKDF2 hashes. The starting account is in `gateway/gateway.xml` (hash only); `python tools/make_user.py` makes the line for a different starting account.
  5 wrong passwords lock a username for 5 minutes. Every sign-in is audited. A deactivated account stops working at once.
- The token secret is generated on first start. The services and the broker accept calls only from the system's own components (the check is written separately in Python, Java and Node.js) (a key made fresh on every start); the broker also limits each component to its own queues.
- Security headers on every response, a strict content policy on the portal, no caching of patient data.
- Before real use: change the starting password at once, serve over HTTPS, and put a rate-limiting proxy in front.

## Everything is a page, not JSON
Any address opened in a browser is a styled page. Programs get JSON only with `Accept: application/json`. XML definitions are styled by `client/xml.xsl`:
browse them at http://localhost:8000/xml (`gateway.xml` is never published).
