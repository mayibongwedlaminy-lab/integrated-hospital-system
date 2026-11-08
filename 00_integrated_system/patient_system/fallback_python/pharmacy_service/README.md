# Pharmacy service (port 8004)

**You own:** prescriptions, the allergy check, the drug-interaction check and dispensing. Database: `pharmacy.db`.
You receive **prescription data and allergy flags only** (no names, no lab results, no diagnoses).

## What the others rely on (the contract)
| Endpoint | Purpose |
|---|---|
| `POST /prescriptions` | comes from the hospital with `patient_id`, `case_id`, `drug`, `dosage`, `allergies`. You answer with `warning` (allergy conflict, or empty) and `interaction` (empty, or `MAJOR: ...`). |
| `GET /prescriptions` | list, filter with `?patient_id=` or `?status=` |
| `PUT /prescriptions/{id}/dispense` | `status` becomes `dispensed`, **and the hospital case is closed** (you call the hospital: see the `<notify>` in `service.xml`). If the hospital is down you still dispense and add `sync_warning`. |

**You call:** the hospital (`PUT /consultations/{case_id}`). **Called by:** the hospital (forwarded prescriptions) and the gateway.

## Where your rules live
- `hooks.py`: `allergy` and `interaction`, written in Python because XML cannot express them. `service.xml` uses them as `hook="allergy,interaction"`.
- `service.xml`: the interaction pairs (`<interactions>`). **A demonstration list, not clinical advice.**

## Messaging (the broker)
Declared in the `<messaging>` block of `service.xml`: no Python needed.
**You send:** `hospital.case-closed` when you dispense (guaranteed delivery: if the hospital is down the message waits), and the events `PrescriptionReceived` and `PrescriptionDispensed`.
**You no longer call the hospital directly.** You never wait for the broker: your outbox keeps the messages until it is back.
See `docs/INTEGRATION.md`.

## Staff and who did it
- **Staff** (`/pharmacists`): the pharmacists. The administrator creates them through the gateway. Every pharmacist sees the same waiting prescriptions.
- `doctor` is the prescribing doctor (stamped from the gateway); `pharmacist` is who dispensed.
- Prescriptions are written on the doctor's side only: the gateway does not let pharmacists create them.

## Good to know
- The portal shows `warning` and `interaction`; the gateway turns them into notifications for the pharmacist and the doctor. Keep the names.

## Ideas to build
- Stock: a `stock` table and a hook that refuses or warns when a drug is out of stock; reduce stock on dispensing.
- Partial dispensing, repeat prescriptions, controlled-drug flag.
- More checks: dose-range, duplicate therapy (same drug twice), interaction severity that blocks dispensing until confirmed.

## How you work
1. `python run.py` in this folder runs **only your service** (port 8004). It needs the header `x-service-key: dev-key`.
2. Change `service.xml` (tables and endpoints) and, only if XML cannot express a rule, `hooks.py` (Python).
3. See your module inside the whole system: from the kit's top folder run `python run.py`, then open http://localhost:8000/ui/
   (your folder is used; the other organisations come from `reference/`).
4. Before you hand over: `python check.py` from the top folder. It must end with **READY TO HAND OVER**.

## Rules
- **Do not edit `engine/` or `contract.xml`.** The engine is the team's shared runtime; the contract is the agreement with the other members.
  If you need a change to either, ask the team lead (see TEAM_GUIDE.md, "Changing the interface").
- Add fields and endpoints freely, but the ones in `contract.xml` must keep working exactly as written.
- Keep to your own data. Never read another organisation's database, and never store its data in your tables.
- The database is `pharmacy.db`, created next to `service.xml` the first time you run. It is ignored by git: delete it to start fresh.

## Hand over
Send back **only this folder** (`pharmacy_service/`), zipped. The team lead puts it into the integrated project and runs `python check.py` and `pytest`.
