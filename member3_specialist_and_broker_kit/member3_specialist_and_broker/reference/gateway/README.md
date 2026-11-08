# Gateway (port 8000)

**You own:** the single front door: sign-in, roles, routing, the audit log, notifications, the patient history, the discharge PDF, and serving the portal.
Database: `gateway.db` (accounts, audit, notifications, lockout counters).

## Your files
| File | What it holds |
|---|---|
| `gateway.xml` | accounts (hashed), security rules, which role may call which route, notification rules, history sources, `<local>` endpoints |
| `gateway.py` | the Python that runs it: login and lockout, role checks, proxying, audit, notifications, history, PDF |
| `engine/` | the team's shared pieces (`pages.py` for styled pages, `report.py` for the PDF). Do not edit. |
| `contract.xml` | the agreed behaviour. Do not edit. |

## What the others rely on
- Services answer only to the gateway (they check a shared key). The gateway sends it automatically.
- The portal relies on every route in `gateway.xml` and every `<local>` endpoint. `python check.py` verifies the portal only uses routes its role may use.
- Notification texts use fields from the services' answers (for example `{test}`, `{drug}`): if a service renames a field, the text breaks.

## Adding a feature that crosses modules
A service member adds an endpoint, then **you add a `<route>`** (and a `<notify>` if people should hear about it) and the **portal owner** adds the screen.

## Messaging (the broker)
- **Store and forward:** a route with `queue="..."` (lab requests, referrals) answers `202 Accepted` and keeps the request in that queue when the service is offline.
- **Notifications:** the gateway listens to the broker's `events` topic and turns each event into a bell notification by the `<notify event="...">` rules.
- **Administrator:** `GET /api/messaging` and `POST /api/messaging/{queue}/retry` show the queues and put dead letters back.

## Accounts, staff and roles
- **One starting account**: `admin` (role administrator) in `gateway.xml`, created once on the very first start with a flag that makes it choose a new password at first sign-in. Everyone else is created by an administrator: `POST /api/staff`. After the first start the database is the truth for accounts (a password reset persists).
- **Several people per role**: each has their own account. `<staff-role>` in `gateway.xml` says which organisation keeps each kind of person's record (working hours, specialty) and which extra fields it keeps. Creating an account also creates that record; if the organisation's service is down, nothing is created.
- **Who is acting**: after checking the token, the gateway tells the service who is acting (`x-user`, `x-role`). Services stamp records with it and apply ownership rules. Services trust only the gateway.
- **Active check on every request**: a deactivated account stops working at once, even with a token it already holds.
- **Passwords**: an account created or reset by an administrator must choose its own password at first sign-in (`must_change`). Anyone can change their own with `POST /api/password`.
- **Notifications can be personal**: `<notify user="doctor">` sends it only to the person named in that field of the event.
- Admin calls: `GET/POST /api/staff`, `PUT /api/staff/{username}`; everyone signed in may read `/api/people` (names for the portal).

## Good to know
- You need the services to test: from the kit's top folder `python run.py` starts them from `reference/` with your gateway in front.
- Never put the token secret or real passwords in `gateway.xml`. Make accounts with `python tools/make_user.py`.

## Ideas to build
- An administrator page to unlock a locked account, or to create accounts.
- Per-IP rate limiting, token refresh, sign-out of all sessions.
- Audit export, filters by user and date, and "who looked at this patient".
- New notification rules, or a daily summary per role.

## How you work, and hand over
1. `python run.py` (top folder) to see your gateway in the whole system.
2. `python check.py` must end with **READY TO HAND OVER** (it runs your contract, `contract.xml`, against the live system).
3. Send back **only `gateway/`**, zipped.
