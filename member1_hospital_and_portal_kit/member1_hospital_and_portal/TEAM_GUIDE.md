# Team guide

## The picture
```
  browser -> portal (client) -> gateway --REST--> hospital service ----> hospital.db      (Python)
                                  |        \--REST--> lab service ------> lab.json        (Java)   <--\
                                  |         \-REST--> specialist -------> specialist.db   (Python)    |  messages
                                  |          \-REST--> pharmacy --------> pharmacy.db     (Node.js)   |  (queues and the
                                  \-- messages --> BROKER (queues, topic "events") <------/   events topic)
                                                       \-- orders / results --> Java lab analyzer
```
Each organisation owns its data. People only reach the system through the gateway. Services answer only to the gateway (and the hospital
calls the pharmacy for the prescription). Everything else between organisations goes through the broker. Read `docs/INTEGRATION.md`.

## Who builds what
Eight modules (folders). With the four people in the design document, a balanced split is one organisation plus one cross-cutting piece each:

| Member | Modules (folders) | In short |
|---|---|---|
| 1 | `hospital_service/` + `client/` | patients, consultations, vitals, diagnoses, appointments; the whole portal |
| 2 | `lab_service/` + `analyzer/` | **Java**: test requests and results; the Java analyzer that joins through the broker |
| 3 | `specialist_service/` + `broker/` | referrals and reports; the message broker (queues, topics, dead letters) |
| 4 | `pharmacy_service/` + `gateway/` | **Node.js** pharmacy: prescriptions, allergy and interaction checks, dispensing; **Python** gateway: sign-in, roles, audit, notifications, history, PDF |
| lead | `contracts/`, `integration/`, `docs/`, `tools/` | the agreements, the shared engine, integration, tests |

Each module folder has a README that says what it owns, what the others rely on, and ideas to build.

## REST or a message?
| If... | use |
|---|---|
| the caller needs the answer to carry on (search, read, the prescription's allergy check) | REST through the gateway |
| the sender only needs to be sure the other side gets it (kept while a service is offline, "dispensed, close the case") | a message to a queue |
| something happened that others may care about (a result is ready) | an event on the `events` topic |
| a different system (like the Java analyzer) needs to take part | queues, with a correlation id for the reply |

## The three rules
1. **Stay in your folder.** You hand back only your folder, so edits elsewhere are lost.
2. **The contract is law.** `contracts/<name>.contract.xml` lists the endpoints and field names the others depend on.
   Your module may do more, but never less or different.
3. **The engine is shared by the Python services.** `engine/` inside the hospital and specialist services is the team's runtime. Do not edit it.
   The laboratory (Java) and the pharmacy (Node.js) have no `engine/`: they are marked by a `module.json` and start through their own `run.py`,
   and they are held to the same contract by `contract.xml` and `python check.py`.

## Day to day
| I want to... | Command |
|---|---|
| run only my service (or gateway) | `python run.py` inside my folder |
| see my module in the whole system | `python run.py` in the top folder, then http://localhost:8000/ui/ |
| know if I am ready | `python check.py` in the top folder |
| run every integration test (lead) | `pytest` (stop any running system first; needs ports 8000 to 8005) |

First sign-in: user `admin`, starting password `admin123` (you must choose a new one). Everyone else is created by the administrator in the portal: Administration, Add staff member.

## Changing the interface
A different field name, a new required field, a new endpoint that others will call:
1. Tell the team and agree it (who calls it, what it returns).
2. The lead edits `contracts/<name>.contract.xml`, raises its `version`, and runs `python integration/sync_modules.py`.
3. Everyone gets the new contracts and re-runs `python check.py`.

**A feature that crosses modules** (example: "record allergy severity"): hospital adds the field and an endpoint
change, the contract gets the new field, the gateway owner adds a `<route>` or a `<notify>` if needed, the client owner adds it to a form in `portal.xml`.

## Integration day (lead)
1. Put every member's folders into one project (replace `hospital_service/`, `client/`, `lab_service/`, `analyzer/`, `specialist_service/`, `broker/`, `pharmacy_service/`, `gateway/` with theirs; keep `contracts/`, `integration/`, `docs/`).
2. `python integration/check_modules.py`: engine and contracts unchanged? If not, see who edited `engine/`.
3. `python check.py`: all seven contracts (eight with Java) and the portal check must pass. A failing line names the step and the reason.
4. `pytest`: the full journey, roles, privacy, security and fault-tolerance tests.
5. `python run.py`, sign in as `admin`, add a receptionist, two doctors (with working days and hours), a lab technician, two specialists of one specialty, and a pharmacist, and click through each role.
6. Fix what is red by asking the owner of that module, not by editing their folder.

## With Git (the monorepo from the SRS)
One repository, one branch per member (`feature/hospital`, `feature/lab`, ...). Because everyone edits only their own folder, merges do not conflict.
Merge into `main` only when `python check.py` passes. `*.db` files and `__pycache__` are ignored.

## If something goes wrong
| Message | Meaning |
|---|---|
| `Port 800x is already in use` | another copy is running; stop it |
| `[FAIL] ... Is it running?` for the broker | start order: `python run.py` starts the broker first; if you run a service alone, the broker is not there and its messages wait in the outbox (nothing is lost) |
| a message stuck in `dead letters` | see the Administration, Messaging tab: read the reason, fix the cause, then press Retry |
| `uses hook 'x' but hooks.py has no such function` | `service.xml` names a hook your `hooks.py` does not define |
| `engine/service.py is not the team's version` | someone edited `engine/`; restore it with `integration/sync_modules.py` |
| `[FAIL] POST /x ... missing fields: ...` | your answer lacks a field in the contract |
| `Module 'x' was not found` | run the command from the top folder; keep `reference/` next to your folder |
