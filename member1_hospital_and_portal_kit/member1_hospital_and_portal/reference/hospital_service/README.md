# Hospital service (port 8001)

**You own:** patient registration, consultations with vital signs, diagnoses and appointments. Database: `hospital.db`.

## What the others rely on (the contract)
| Endpoint | Purpose |
|---|---|
| `POST /patients`, `GET /patients`, `GET /patients/{id}`, `PUT /patients/{id}` | register (national ID must be unique, else 409), search (`?national_id=`), read, edit |
| `POST /consultations`, `GET /consultations`, `GET /consultations/{id}`, `PUT /consultations/{id}` | a visit: `symptoms`, `temp`, `bp_sys`, `bp_dia`, `pulse`, `spo2`, `status` (open, closed) |
| `POST /diagnoses`, `GET /diagnoses` | a doctor's diagnosis for a patient |
| `POST /appointments`, `GET /appointments`, `PUT /appointments/{id}` | `date`, `time`, `reason`, `status` (scheduled, completed, cancelled) |
| `POST /prescriptions` | **forwarded to the pharmacy**, with the patient's `allergies` added from your patients table. The answer is the pharmacy's. |

**Other organisations call you:** the pharmacy calls `PUT /consultations/{id}` with `status=closed` when it dispenses.
**You call:** the pharmacy (`POST /prescriptions`). Everything else reaches you through the gateway.

## Messaging (the broker)
Declared in the `<messaging>` block of `service.xml`: no Python needed.
**You receive:** `hospital.case-closed` (from the pharmacy: `{case_id, status: closed}`), handled by your own `PUT /consultations/{id}`.
**You announce** on the `events` topic: `AppointmentBooked`.
**You still call by REST:** the pharmacy (`POST /prescriptions`), because the doctor needs the allergy answer at once.
See `docs/INTEGRATION.md`.

## Staff, roles and who did it
- **Staff** (`/staff`): the hospital's doctors and receptionists. A doctor has working days, working hours and a slot length (`working_days`, `start`, `end`, `slot_minutes`). The administrator creates them through the gateway, which also creates the sign-in account.
- **Only receptionists register patients.** The gateway enforces it (`POST /patients` is a receptionist route). Receptionists and doctors may correct details.
- **Appointments are booked against the doctors' availability** (`hooks.py`, `schedule`): the doctor asked for if free; otherwise another doctor free at that very time; otherwise the next free slot in the next 30 days. The answer says what happened in `note`.
- **Time off** (`/time-off`): a doctor marks days they are unavailable; booking skips them. Only that doctor can change it.
- **A consultation belongs to the doctor who started it** (`doctor` is stamped from the gateway's `x-user`). Only that doctor may treat (`PUT /consultations/{id}/diagnosis`) or close it. A doctor **treats** (diagnosis and treatment plan) or **refers**; `outcome` then reads `treating`, `referred`, `treated by specialist` or `treatment recommended`.
- `stamp="column"` in `service.xml` records who did something; `scope="role:column"` limits a list to that person's rows.

## Good to know
- The portal's vital-sign charts read `temp`, `bp_sys`, `bp_dia`, `pulse`, `spo2` from consultations: keep those names.
- The gateway's notification texts use `date`, `time` and `patient_id` from appointments.
- You never store lab results, reports or drugs: the contract's privacy list checks that.

## Ideas to build (each is yours to design)
- Ward and bed management (a `beds` table and endpoints), or a waiting-list for appointments.
- Validation of the national ID format in `hooks.py` (see the example inside it).
- Patient merge, archive or "date of death" handling; next of kin and emergency contact fields.
- Appointment clashes: refuse two appointments at the same date and time.

## How you work
1. `python run.py` in this folder runs **only your service** (port 8001). It needs the header `x-service-key: dev-key`.
2. Change `service.xml` (tables and endpoints) and, only if XML cannot express a rule, `hooks.py` (Python).
3. See your module inside the whole system: from the kit's top folder run `python run.py`, then open http://localhost:8000/ui/
   (your folder is used; the other organisations come from `reference/`).
4. Before you hand over: `python check.py` from the top folder. It must end with **READY TO HAND OVER**.

## Rules
- **Do not edit `engine/` or `contract.xml`.** The engine is the team's shared runtime; the contract is the agreement with the other members.
  If you need a change to either, ask the team lead (see TEAM_GUIDE.md, "Changing the interface").
- Add fields and endpoints freely, but the ones in `contract.xml` must keep working exactly as written.
- Keep to your own data. Never read another organisation's database, and never store its data in your tables.
- The database is `hospital.db`, created next to `service.xml` the first time you run. It is ignored by git: delete it to start fresh.

## Hand over
Send back **only this folder** (`hospital_service/`), zipped. The team lead puts it into the integrated project and runs `python check.py` and `pytest`.
