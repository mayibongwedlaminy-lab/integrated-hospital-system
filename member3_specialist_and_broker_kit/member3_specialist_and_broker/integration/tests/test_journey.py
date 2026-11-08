"""The patient journey from the design document, through the gateway, by the people who do each step."""
import io
from pypdf import PdfReader
from conftest import eventually

state = {}


def test_01_a_receptionist_registers_the_patient(api):
    r = api("reception1").post("/patients", json={"national_id": "9001019999", "name": "Journey Patient", "dob": "1990-01-01", "allergies": "penicillin"})
    assert r.status_code == 200 and r.json()["registered_by"] == "reception1"
    state["pid"] = r.json()["id"]


def test_02_duplicate_national_id_is_refused(api):
    assert api("reception2").post("/patients", json={"national_id": "9001019999", "name": "Copy"}).status_code == 409


def test_03_search_and_edit(api):
    found = api("dr_dlamini").get("/patients", params={"national_id": "9001019999"}).json()
    assert [p["name"] for p in found] == ["Journey Patient"]
    r = api("dr_dlamini").put(f"/patients/{state['pid']}", json={"allergies": "penicillin, latex"})  # a doctor may correct details
    assert r.json()["allergies"] == "penicillin, latex"


def test_04_the_doctor_starts_a_consultation_with_vitals(api):
    r = api("dr_dlamini").post("/consultations", json={"patient_id": state["pid"], "symptoms": "fever", "temp": "38.6", "bp_sys": "120", "bp_dia": "80", "pulse": "95", "spo2": "97"})
    assert r.json()["status"] == "open" and r.json()["doctor"] == "dr_dlamini" and r.json()["temp"] == "38.6"
    state["case"] = r.json()["id"]


def test_05_lab_request_and_result_by_a_technician(api):
    req = api("dr_dlamini").post("/lab/requests", json={"patient_id": state["pid"], "case_id": state["case"], "test": "Malaria"}).json()
    assert req["requested_by"] == "dr_dlamini"
    done = api("lab2").put(f"/lab/results/{req['id']}", json={"result": "negative"}).json()
    assert done["status"] == "completed" and done["technician"] == "lab2"


def test_06_the_doctor_treats(api):
    r = api("dr_dlamini").put(f"/consultations/{state['case']}/diagnosis", json={"diagnosis": "Otitis media", "treatment": "Antibiotics for 5 days"}).json()
    assert r["outcome"] == "treating" and r["diagnosis"] == "Otitis media"


def test_07_prescription_is_checked_against_allergies(api):
    r = api("dr_dlamini").post("/prescriptions", json={"patient_id": state["pid"], "case_id": state["case"], "drug": "Penicillin V", "dosage": "500 mg"}).json()
    assert r["warning"].startswith("ALLERGY CONFLICT") and "penicillin" in r["warning"] and r["doctor"] == "dr_dlamini"
    state["rx"] = r["id"]


def test_08_drug_interaction_is_flagged(api):
    api("dr_dlamini").post("/prescriptions", json={"patient_id": state["pid"], "case_id": state["case"], "drug": "Aspirin 75 mg", "dosage": "daily"})
    r = api("dr_dlamini").post("/prescriptions", json={"patient_id": state["pid"], "case_id": state["case"], "drug": "Warfarin 5 mg", "dosage": "daily"}).json()
    assert r["interaction"].startswith("MAJOR") and "Aspirin" in r["interaction"]


def test_09_a_pharmacist_dispenses_and_the_case_closes_by_message(api):
    r = api("pharm2").put(f"/prescriptions/{state['rx']}/dispense").json()
    assert r["status"] == "dispensed" and r["pharmacist"] == "pharm2"
    eventually(lambda: [c["status"] for c in api("dr_dlamini").get("/consultations", params={"patient_id": state["pid"]}).json()] == ["closed"])


def test_10_full_history_gathers_every_organisation(api):
    h = api("dr_dlamini").get(f"/api/patients/{state['pid']}/full-history").json()
    assert h["patient"]["name"] == "Journey Patient"
    assert all(isinstance(h[k], list) and h[k] for k in ("consultations", "lab_tests", "prescriptions"))
    assert h["appointments"] == []


def test_11_discharge_summary_pdf(api):
    r = api("dr_dlamini").get(f"/api/cases/{state['case']}/discharge.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
    for needle in ("Journey Patient", "Malaria", "Penicillin V", "38.6"):
        assert needle in text
    assert api("dr_dlamini").get("/api/cases/99999/discharge.pdf").status_code == 404


def test_12_notifications_go_to_the_right_person(api):
    texts = lambda u: [n["text"] for n in api(u).get("/notifications").json()]  # events travel through the broker: they arrive a moment later
    eventually(lambda: any("Lab result ready: Malaria" in t for t in texts("dr_dlamini")))
    eventually(lambda: any("ALLERGY WARNING" in t for t in texts("pharm1")) and any("ALLERGY WARNING" in t for t in texts("pharm2")))  # every pharmacist
    eventually(lambda: any("Allergy warning on your prescription" in t for t in texts("dr_dlamini")))
    assert not any("Lab result ready" in t or "Allergy warning on your" in t for t in texts("dr_nkosi")), "another doctor must not hear about Dr Dlamini's patient"
    assert not any("Journey" in t for t in texts("lab1")), "notifications carry patient numbers, never names"


def test_13_notifications_can_be_marked_read(api, system):
    c = system.client("pharm1")
    eventually(lambda: any(n["unread"] for n in c.get("/notifications").json()))
    c.post("/notifications/read")
    assert not any(n["unread"] for n in c.get("/notifications").json())


def test_14_every_action_was_audited_with_who_did_it(api):
    log = api("admin").get("/audit").json()
    assert any(r["path"] == "/prescriptions" and r["user"] == "dr_dlamini" and r["method"] == "POST" for r in log)
    assert any(r["path"] == "/patients" and r["user"] == "reception1" and r["method"] == "POST" for r in log)
    assert any(r["path"] == "/api/cases/%d/discharge.pdf" % state["case"] for r in log)
