# Specialist service (port 8003)

**You own:** referrals to specialist clinics and the expert reports that come back. Database: `specialist.db`. Like the lab, you only know a **patient number**.

## What the others rely on (the contract)
| Endpoint | Purpose |
|---|---|
| `POST /referrals` | a doctor refers a patient: `patient_id`, `specialty`, `reason`. Starts as `status=pending`. |
| `GET /referrals` | list, filter with `?patient_id=` or `?status=` |
| `PUT /referrals/{id}/report` | the specialist writes `report`; the status becomes `reported` |

**You call:** nobody. **Called by:** the gateway only.

## Messaging (the broker)
Declared in the `<messaging>` block of `service.xml`: no Python needed.
**You receive:** `specialist.referrals` (referrals the gateway kept while you were offline).
**You announce:** `ReferralSent` and `ReportReady`.
See `docs/INTEGRATION.md`.

## Specialists, specialties and what they do
- **Staff** (`/specialists`): each specialist has a **specialty** (ENT, Cardiology, ...). The administrator creates them through the gateway.
- **A referral goes to a specialist of the specialty asked for** (`hooks.py`, `assign_specialist`): the one the doctor named, or else the one with the fewest waiting referrals. If nobody has that specialty, the doctor gets a clear refusal (409).
- **A specialist only sees the referrals assigned to them** (`scope="specialist:specialist"` on the list), and only the assigned specialist can answer.
- **The answer says what was done**: `action` = `treated` (the specialist treated the patient) or `recommended` (a treatment is recommended to the referring doctor), with `report` (findings) and `treatment`. The hospital consultation shows the outcome through the broker.

## Good to know
- The portal and the patient history show `specialty`, `reason`, `report`, `status`: keep those names.
- Never return a patient's name, ID number, date of birth, allergies, drugs or lab results.

## Ideas to build
- A clinics table (specialty, clinic name, days open) and referral **urgency** (routine, urgent).
- Decline or reassign a referral to another specialty; a reason for declining.
- Waiting-time field and a report template per specialty.

## How you work
1. `python run.py` in this folder runs **only your service** (port 8003). It needs the header `x-service-key: dev-key`.
2. Change `service.xml` (tables and endpoints) and, only if XML cannot express a rule, `hooks.py` (Python).
3. See your module inside the whole system: from the kit's top folder run `python run.py`, then open http://localhost:8000/ui/
   (your folder is used; the other organisations come from `reference/`).
4. Before you hand over: `python check.py` from the top folder. It must end with **READY TO HAND OVER**.

## Rules
- **Do not edit `engine/` or `contract.xml`.** The engine is the team's shared runtime; the contract is the agreement with the other members.
  If you need a change to either, ask the team lead (see TEAM_GUIDE.md, "Changing the interface").
- Add fields and endpoints freely, but the ones in `contract.xml` must keep working exactly as written.
- Keep to your own data. Never read another organisation's database, and never store its data in your tables.
- The database is `specialist.db`, created next to `service.xml` the first time you run. It is ignored by git: delete it to start fresh.

## Hand over
Send back **only this folder** (`specialist_service/`), zipped. The team lead puts it into the integrated project and runs `python check.py` and `pytest`.
