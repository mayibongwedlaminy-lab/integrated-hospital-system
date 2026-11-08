"""Runs last (the name sorts last): it stops services and brings them back. The tests depend on each other, in order."""
from conftest import eventually

state = {}


def test_01_one_service_down_only_breaks_its_own_routes(system, api, patient):
    state["pid"] = patient["id"]
    system.stop_one("lab_service")
    doc = api("dr_dlamini")
    r = doc.get("/lab/requests")
    assert r.status_code == 503 and "unavailable" in r.json()["detail"]
    assert doc.get("/patients").status_code == 200  # hospital still works
    assert doc.get("/prescriptions").status_code == 200  # pharmacy still works


def test_02_history_degrades_instead_of_failing(api):
    h = api("dr_dlamini").get(f"/api/patients/{state['pid']}/full-history").json()
    assert h["lab_tests"] == "unavailable" and isinstance(h["consultations"], list) and isinstance(h["prescriptions"], list)


def test_03_status_lights_show_the_outage(api):
    assert api("dr_dlamini").get("/api/status").json() == {"hospital": True, "laboratory": False, "specialist": True, "pharmacy": True, "broker": True}


def test_04_a_request_for_an_offline_service_is_kept_not_refused(api):
    # the design document: "A request stays pending until the service can process it"
    r = api("dr_dlamini").post("/lab/requests", json={"patient_id": 4242, "test": "Full blood count"})
    assert r.status_code == 202 and r.json()["queued"] is True and "delivered automatically" in r.json()["detail"]
    assert any(x["status"] == 202 for x in api("admin").get("/audit").json())


def test_05_the_kept_request_is_delivered_when_the_service_returns(api, system):
    system.restart("lab_service")
    found = eventually(lambda: [x for x in api("dr_dlamini").get("/lab/requests", params={"patient_id": 4242}).json() if x["test"] == "Full blood count"])
    assert len(found) == 1 and found[0]["status"] == "pending" and found[0]["requested_by"] == "dr_dlamini"  # exactly once, still the same doctor
    assert api("dr_dlamini").get("/api/status").json()["laboratory"] is True


def test_06_a_prescription_needs_an_immediate_answer_so_it_is_refused_not_queued(api, system):
    system.stop_one("pharmacy_service")
    r = api("dr_dlamini").post("/prescriptions", json={"patient_id": state["pid"], "case_id": 1, "drug": "Paracetamol", "dosage": "500 mg"})
    assert r.status_code == 503
    system.restart("pharmacy_service")


def test_07_nothing_is_lost_while_the_broker_is_down(api, system):
    pid = api("reception2").post("/patients", json={"national_id": "9911119911", "name": "Outage Patient"}).json()["id"]
    case = api("dr_dlamini").post("/consultations", json={"patient_id": pid, "symptoms": "cough"}).json()["id"]
    rx = api("dr_dlamini").post("/prescriptions", json={"patient_id": pid, "case_id": case, "drug": "Cough syrup", "dosage": "10 ml"}).json()["id"]
    system.stop_one("broker")
    r = api("pharm1").put(f"/prescriptions/{rx}/dispense")
    assert r.status_code == 200 and r.json()["status"] == "dispensed"  # the pharmacy does not need the broker to do its own work
    assert [c["status"] for c in api("dr_dlamini").get("/consultations", params={"patient_id": pid}).json()] == ["open"]  # the hospital has not heard yet
    system.restart("broker")
    eventually(lambda: [c["status"] for c in api("dr_dlamini").get("/consultations", params={"patient_id": pid}).json()] == ["closed"], timeout=40)
    eventually(lambda: any("Dispensed: Cough syrup" in n["text"] for n in api("dr_dlamini").get("/notifications").json()), timeout=40)
