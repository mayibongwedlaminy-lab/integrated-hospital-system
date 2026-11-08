# Pharmacy service (port 8004), written in Node.js

**You own:** prescriptions, the allergy check, the drug-interaction check and dispensing. Database: `pharmacy.db` (SQLite, Node's built-in `node:sqlite`).
You receive **prescription data and allergy flags only** (no names, no lab results, no diagnoses).
**Language:** Node.js 22.13 or newer, Express. `python run.py` installs the two npm packages the first time.

## What the others rely on (the contract)
| Endpoint | Purpose |
|---|---|
| `POST /prescriptions` | comes from the hospital with `patient_id`, `case_id`, `drug`, `dosage`, `allergies`. Answered at once with `warning` (allergy conflict, or empty) and `interaction` (empty, or `MAJOR: ...`) |
| `GET /prescriptions` | list, filter with `?patient_id=` or `?status=` |
| `PUT /prescriptions/{id}/dispense` | `status` becomes `dispensed`, **and the hospital case is closed**: a message to `hospital.case-closed` is saved in the same transaction as the change (outbox), so it is delivered even if the broker or the hospital is down |
| `POST/GET/PUT /pharmacists` | the pharmacy's own pharmacists |

## The code
| File | Job |
|---|---|
| `server.js` | Express app: the service-key check, routes, the two business operations (create and dispense) |
| `src/rules.js` | the allergy and interaction rules (pure functions, unit-tested) |
| `src/store.js` | SQLite tables from `service.xml`, transactions, and the outbox (`announce`) |
| `src/relay.js` | sends the outbox to the broker in order; keeps messages while the broker is down |
| `src/config.js` | reads `service.xml`: tables, messages and the interaction pairs |
| `test/rules.test.js` | `npm test` |

`service.xml` still declares the tables, the messages and the interaction pairs (**a demonstration list, not clinical advice**); Node reads it, so there is one place to change them.

## How you work
1. `python run.py` in this folder runs **only the pharmacy** (port 8004). Calls need the header `x-service-key: dev-key`. Or: `npm install` then `PPS_SERVICE_KEY=dev-key node server.js`.
2. `npm test` runs the rule tests.
3. See it in the whole system: from the top folder run `python run.py`, then open http://localhost:8000/ui/
4. Before you hand over: `python check.py` from the top folder. It must end with **READY TO HAND OVER**.

## Rules
- **Do not edit `contract.xml`.** It is the agreement with the other members. Add fields and endpoints freely, but the ones in the contract must keep working exactly as written.
- Keep to your own data. Never read another organisation's database, and never store its data in your tables.
- `pharmacy.db` is created in the data folder the first time you run; it is ignored by git. `node_modules/` is not committed: `npm install` recreates it.

## Ideas to build
- Stock: a `stock` table and a rule that warns when a drug is out of stock; reduce stock on dispensing.
- Partial dispensing, repeat prescriptions, controlled-drug flag, dose-range and duplicate-therapy checks.
