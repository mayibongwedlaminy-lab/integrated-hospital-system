"""Appointments are booked against the doctors' availability; if the doctor is not free, the next available doctor (or slot) is used.
Schedules (see conftest): dr_dlamini Mon-Fri 08:00-16:00, dr_nkosi Mon-Wed 10:00-18:00, dr_mamba Thu-Sat 08:00-14:00, 30-minute slots."""
from datetime import timedelta
import pytest
from conftest import MONDAY, eventually

D = lambda days: (MONDAY + timedelta(days=days)).isoformat()


@pytest.fixture(scope="module")
def pid(patient):
    return patient["id"]


def book(api, pid, **b):
    return api("reception1").post("/appointments", json={"patient_id": pid, "reason": "check", **b})


def test_the_doctor_asked_for_is_booked_when_free(api, pid):
    r = book(api, pid, doctor="dr_dlamini", date=D(0), time="09:00")
    assert r.status_code == 200 and r.json()["doctor"] == "dr_dlamini" and r.json()["note"] == "" and r.json()["booked_by"] == "reception1"


def test_a_busy_doctor_gives_way_to_another_doctor_free_at_that_time(api, pid):
    book(api, pid, doctor="dr_dlamini", date=D(0), time="10:00")  # dlamini is now busy at 10:00
    r = book(api, pid, doctor="dr_dlamini", date=D(0), time="10:00").json()
    assert r["doctor"] == "dr_nkosi" and r["time"] == "10:00" and "not available then" in r["note"] and "Dr. Sipho Dlamini" in r["note"]


def test_when_nobody_is_free_the_next_available_slot_is_booked(api, pid):
    r = book(api, pid, doctor="dr_dlamini", date=D(0), time="10:00").json()  # dlamini and nkosi are both taken at 10:00; mamba does not work Mondays
    assert r["date"] == D(0) and r["time"] == "10:30" and "next available slot" in r["note"]


def test_a_doctor_who_does_not_work_that_day_is_replaced_by_one_who_does(api, pid):
    r = book(api, pid, doctor="dr_dlamini", date=D(5), time="09:00").json()  # Saturday: only dr_mamba works
    assert r["doctor"] == "dr_mamba" and r["date"] == D(5) and "not available then" in r["note"]


def test_when_no_doctor_works_that_day_the_next_working_day_is_booked(api, pid):
    r = book(api, pid, date=D(6), time="09:00").json()  # Sunday: nobody works
    assert r["date"] == D(7) and r["doctor"] == "dr_dlamini" and r["time"] == "08:00" and "next available slot" in r["note"]


def test_a_time_inside_a_slot_moves_to_the_start_of_the_slot(api, pid):
    r = book(api, pid, doctor="dr_mamba", date=D(3), time="09:10").json()  # Thursday
    assert r["time"] == "09:00" and "moved to the start of the slot" in r["note"]


def test_a_doctor_can_mark_time_off_and_is_then_not_booked(api, pid):
    assert api("dr_dlamini").post("/time-off", json={"date_from": D(1), "date_to": D(2), "reason": "conference"}).status_code == 200
    r = book(api, pid, doctor="dr_dlamini", date=D(1), time="11:00").json()  # Tuesday: dlamini is off, nkosi works
    assert r["doctor"] == "dr_nkosi" and "not available then" in r["note"]
    off = api("dr_dlamini").get("/time-off").json()[0]
    assert off["doctor"] == "dr_dlamini" and off["status"] == "active"


def test_time_off_belongs_to_the_doctor_who_made_it(api):
    off = [o for o in api("dr_dlamini").get("/time-off").json() if o["status"] == "active"][0]
    assert api("dr_nkosi").put(f"/time-off/{off['id']}", json={"status": "cancelled"}).status_code == 403
    assert api("reception1").post("/time-off", json={"date_from": D(0), "date_to": D(0)}).status_code == 403
    assert api("dr_dlamini").put(f"/time-off/{off['id']}", json={"status": "cancelled"}).json()["status"] == "cancelled"


def test_bad_requests_are_refused_with_a_reason(api, pid):
    assert book(api, pid, date="2001-01-01", time="09:00").status_code == 422
    assert book(api, pid, date="not-a-date", time="09:00").status_code == 422
    assert book(api, pid, doctor="dr_nobody", date=D(0), time="11:00").status_code == 422
    assert api("dr_dlamini").post("/time-off", json={"date_from": D(3), "date_to": D(1)}).status_code == 422


def test_a_deactivated_doctor_is_never_booked(api, pid):
    assert api("admin").put("/api/staff/dr_mamba", json={"active": "no"}).status_code == 200
    try:
        r = book(api, pid, doctor="dr_mamba", date=D(3), time="12:00")
        assert r.status_code == 422
        assert book(api, pid, date=D(5), time="12:00").json()["doctor"] != "dr_mamba"  # Saturday: mamba was the only one
    finally:
        api("admin").put("/api/staff/dr_mamba", json={"active": "yes"})


def test_only_the_booked_doctor_is_told(api, pid):
    r = book(api, pid, doctor="dr_nkosi", date=D(2), time="16:00").json()  # Wednesday
    assert r["doctor"] == "dr_nkosi"
    eventually(lambda: any(f"New appointment on {D(2)} at 16:00" in n["text"] for n in api("dr_nkosi").get("/notifications").json()))
    assert not any(f"at 16:00, patient #{pid}" in n["text"] and D(2) in n["text"] for n in api("dr_mamba").get("/notifications").json())


def test_nobody_on_the_staff_list_means_a_clear_refusal(api, system, pid):
    # a doctor with no working days or hours can not be booked
    api("admin").post("/api/staff", json={"username": "dr_unscheduled", "role": "doctor", "full_name": "Dr. No Hours", "password": "long-enough-1"})
    row = next(s for s in api("admin").get("/api/staff").json() if s["username"] == "dr_unscheduled")
    assert "cannot be booked" in row["note"]
    assert book(api, pid, doctor="dr_unscheduled", date=D(0), time="09:00").json()["doctor"] != "dr_unscheduled"
