# Laboratory service (port 8002)

**You own:** test requests and their results. Database: `lab.db`. The lab only ever knows a **patient number**, never a name.

## What the others rely on (the contract)
| Endpoint | Purpose |
|---|---|
| `POST /lab/requests` | a doctor asks for a test: `patient_id`, `test`. Starts as `status=pending`. |
| `GET /lab/requests` | list, filter with `?patient_id=` or `?status=` |
| `PUT /lab/results/{id}` | the technician enters `result`; the status becomes `completed` |

**You call:** nobody. **Called by:** the gateway only.

## Messaging (the broker)
Declared in the `<messaging>` block of `service.xml`: no Python needed.
**You receive:** `lab.requests` (requests the gateway kept while you were offline, handled exactly like `POST /lab/requests`) and `lab.analyzer.results` (results from the Java analyzer, handled by `PUT /lab/results/{request_id}`).
**You send:** an order to `lab.analyzer.orders` for automated tests, and the events `LabRequested` and `LabResultReady`.
See `docs/INTEGRATION.md`.

## Staff and who did it
- **Staff** (`/lab/staff`): the technicians. The administrator creates them through the gateway. Any technician can take any waiting request.
- `requested_by` is the doctor who asked (stamped from the gateway); `technician` is who entered the result. Results from the Java analyzer are signed `analyzer`.
- A request can carry the consultation number (`case_id`).

## Good to know
- The doctor's dashboard and the patient history show `test`, `result`, `status`: keep those names.
- Notification texts use `test` and `patient_id`.
- Never return a patient's name, ID number, date of birth, allergies or diagnosis: the contract's privacy list checks that.

## Ideas to build
- A test catalogue (`tests` table) with sample type and **reference ranges**, and a hook that flags abnormal results.
- Priority (urgent, routine) and a turnaround-time field; sample collected / received steps.
- Batch result entry, or amended results that keep the old value.

## How you work
1. `python run.py` in this folder runs **only your service** (port 8002). It needs the header `x-service-key: dev-key`.
2. Change `service.xml` (tables and endpoints) and, only if XML cannot express a rule, `hooks.py` (Python).
3. See your module inside the whole system: from the kit's top folder run `python run.py`, then open http://localhost:8000/ui/
   (your folder is used; the other organisations come from `reference/`).
4. Before you hand over: `python check.py` from the top folder. It must end with **READY TO HAND OVER**.

## Rules
- **Do not edit `engine/` or `contract.xml`.** The engine is the team's shared runtime; the contract is the agreement with the other members.
  If you need a change to either, ask the team lead (see TEAM_GUIDE.md, "Changing the interface").
- Add fields and endpoints freely, but the ones in `contract.xml` must keep working exactly as written.
- Keep to your own data. Never read another organisation's database, and never store its data in your tables.
- The database is `lab.db`, created next to `service.xml` the first time you run. It is ignored by git: delete it to start fresh.

## Hand over
Send back **only this folder** (`lab_service/`), zipped. The team lead puts it into the integrated project and runs `python check.py` and `pytest`.
