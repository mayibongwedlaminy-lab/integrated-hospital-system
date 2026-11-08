"""Hospital rules written in Python (only what service.xml cannot express). service.xml uses them as  hook="name".

A hook gets  row (a dict, changed in place),  run(sql, args) for this service's database,  the service.xml root,
actor ({"user", "role"} of whoever is acting, or None for the system itself) and action ("insert" or "update").
To refuse something, raise HTTPException."""
from datetime import date, timedelta
from fastapi import HTTPException

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
LOOKAHEAD_DAYS = 30


def mins(hhmm):
    h, m = str(hhmm).split(":")
    return int(h) * 60 + int(m)


def hhmm(n):
    return f"{n // 60:02d}:{n % 60:02d}"


def slots(doc):
    """Start times (in minutes) of every slot in this doctor's working day."""
    try:
        step = int(doc["slot_minutes"] or 30)
        return list(range(mins(doc["start"]), mins(doc["end"]) - step + 1, step))
    except (ValueError, KeyError, TypeError):
        return []  # no schedule set: this doctor can not be booked


def schedule(row, run, root, actor, action):
    """Book an appointment against the doctors' availability.
    1. the doctor asked for, if free at that date and time
    2. otherwise another doctor who is free at that very time (the one with the lightest day)
    3. otherwise the next slot, in the next 30 days, with any doctor"""
    if action != "insert":
        return
    try:
        want_day, want = date.fromisoformat(row["date"]), mins(row["time"])
    except (ValueError, KeyError, AttributeError):
        raise HTTPException(422, "Give the date as YYYY-MM-DD and the time as HH:MM.")
    if want_day < date.today():
        raise HTTPException(422, "That date has already passed.")
    doctors = run("SELECT * FROM staff WHERE role='doctor' AND active='yes' ORDER BY username")[0]
    if not doctors:
        raise HTTPException(409, "There are no doctors on the staff list.")
    preferred = row.get("doctor") or ""
    if preferred and preferred not in {d["username"] for d in doctors}:
        raise HTTPException(422, f"'{preferred}' is not an active doctor.")
    off = run("SELECT * FROM time_off WHERE status='active'")[0]
    booked = run("SELECT doctor, date, time FROM appointments WHERE status='scheduled'")[0]
    taken = {(b["doctor"], b["date"], b["time"]) for b in booked}
    load = {}
    for b in booked:
        load[(b["doctor"], b["date"])] = load.get((b["doctor"], b["date"]), 0) + 1

    def free(doc, day, m):
        iso = day.isoformat()
        return (DAYS[day.weekday()] in str(doc["working_days"]).split(",") and m in slots(doc)
                and not any(o["doctor"] == doc["username"] and o["date_from"] <= iso <= o["date_to"] for o in off)
                and (doc["username"], iso, hhmm(m)) not in taken)

    def slot_of(doc, m):  # the slot that contains this time, or None
        return next((s for s in slots(doc) if s <= m < s + int(doc["slot_minutes"] or 30)), None)

    chosen = None
    for doc in sorted(doctors, key=lambda d: (d["username"] != preferred, load.get((d["username"], row["date"]), 0), d["username"])):
        m = slot_of(doc, want)
        if m is not None and free(doc, want_day, m):
            chosen = (doc, want_day, m)
            break
    if chosen:
        doc, day, m = chosen
        note = ""
        if preferred and doc["username"] != preferred:
            asked = next(d["full_name"] for d in doctors if d["username"] == preferred)
            note = f"{asked} is not available then, so this is booked with {doc['full_name']}."
        if m != want:
            note = (note + f" The time was moved to the start of the slot, {hhmm(m)}.").strip()
    else:
        for offset in range(LOOKAHEAD_DAYS + 1):
            day = want_day + timedelta(days=offset)
            found = [(m, d["username"] != preferred, load.get((d["username"], day.isoformat()), 0), d["username"], d)
                     for d in doctors for m in slots(d) if (offset or m > want) and free(d, day, m)]
            if found:
                m, _, _, _, doc = min(found, key=lambda f: f[:4])
                break
        else:
            raise HTTPException(409, f"No doctor has a free slot in the next {LOOKAHEAD_DAYS} days.")
        note = f"No doctor is free on {row['date']} at {row['time']}, so this is the next available slot, with {doc['full_name']}."
    row["requested_doctor"], row["doctor"] = preferred, doc["username"]
    row["date"], row["time"], row["note"] = day.isoformat(), hhmm(m), note


def own_case(row, run, root, actor, action):
    """A consultation can only be changed by the doctor who owns it (the system itself, for example closing it on dispensing, may)."""
    if action == "update" and actor and actor["role"] == "doctor" and row.get("doctor") and row["doctor"] != actor["user"]:
        raise HTTPException(403, "This consultation belongs to another doctor.")


def own_time_off(row, run, root, actor, action):
    if action == "update" and actor and actor["role"] == "doctor" and row.get("doctor") != actor["user"]:
        raise HTTPException(403, "That time off belongs to another doctor.")
    try:
        if date.fromisoformat(row["date_from"]) > date.fromisoformat(row["date_to"]):
            raise HTTPException(422, "The last day is before the first day.")
    except (ValueError, KeyError):
        raise HTTPException(422, "Give the dates as YYYY-MM-DD.")


def valid_staff(row, run, root, actor, action):
    if row.get("role") not in ("doctor", "receptionist"):
        raise HTTPException(422, "The hospital staff list holds doctors and receptionists.")
    if row.get("active") not in ("yes", "no"):
        raise HTTPException(422, "active must be yes or no.")
    days = [d for d in str(row.get("working_days") or "").split(",") if d]
    if any(d not in DAYS for d in days):
        raise HTTPException(422, "Working days must be from: " + ", ".join(DAYS))
    if row.get("start") or row.get("end"):
        try:
            if mins(row["start"]) >= mins(row["end"]):
                raise HTTPException(422, "The working day must end after it starts.")
            if not 5 <= int(row.get("slot_minutes") or 30) <= 120:
                raise HTTPException(422, "A slot is between 5 and 120 minutes.")
        except (ValueError, KeyError, AttributeError):
            raise HTTPException(422, "Give start and end as HH:MM and the slot length in minutes.")


HOOKS = {"schedule": schedule, "own_case": own_case, "own_time_off": own_time_off, "valid_staff": valid_staff}
