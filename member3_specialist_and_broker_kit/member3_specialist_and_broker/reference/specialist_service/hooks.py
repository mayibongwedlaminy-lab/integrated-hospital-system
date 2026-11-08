"""Specialist clinic rules written in Python. service.xml uses them as  hook="name"  (see hospital_service/hooks.py for the hook signature)."""
from fastapi import HTTPException


def assign_specialist(row, run, root, actor, action):
    """A referral goes to a specialist of the right specialty: the one the doctor named, or else the one with the fewest waiting referrals."""
    if action != "insert":
        return
    specialty = row.get("specialty") or ""
    pool = run("SELECT username, full_name FROM staff WHERE specialty=? AND active='yes' ORDER BY username", (specialty,))[0]
    if not pool:
        raise HTTPException(409, f"No {specialty or 'such'} specialist is available.")
    if row.get("specialist") in {p["username"] for p in pool}:
        return  # the doctor named a specialist of that specialty
    waiting = {p["username"]: run("SELECT COUNT(*) AS n FROM referrals WHERE specialist=? AND status='pending'", (p["username"],))[0][0]["n"] for p in pool}
    row["specialist"] = min(pool, key=lambda p: (waiting[p["username"]], p["username"]))["username"]


def answer_referral(row, run, root, actor, action):
    """Only the assigned specialist answers, and says what they did: treated the patient, or recommended a treatment to the doctor."""
    if action != "update":
        return
    if actor and actor["role"] == "specialist" and row.get("specialist") != actor["user"]:
        raise HTTPException(403, "This referral is assigned to another specialist.")
    if row.get("action") not in ("treated", "recommended"):
        raise HTTPException(422, "Say what you did: treated the patient, or recommended a treatment.")
    if not (row.get("report") or "").strip() or not (row.get("treatment") or "").strip():
        raise HTTPException(422, "Write your findings (report) and the treatment given or recommended.")


def valid_staff(row, run, root, actor, action):
    if not (row.get("specialty") or "").strip():
        raise HTTPException(422, "A specialist needs a specialty.")
    if row.get("active") not in ("yes", "no"):
        raise HTTPException(422, "active must be yes or no.")


HOOKS = {"assign_specialist": assign_specialist, "answer_referral": answer_referral, "valid_staff": valid_staff}
