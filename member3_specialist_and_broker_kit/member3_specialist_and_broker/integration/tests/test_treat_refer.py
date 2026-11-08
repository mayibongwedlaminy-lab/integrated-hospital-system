"""A doctor treats or refers. The referral goes to a specialist of that specialty, who treats the patient or recommends treatment."""
from conftest import eventually

state = {}


def test_setup(api, patient):
    state["pid"] = patient["id"]
    c = api("dr_dlamini").post("/consultations", json={"patient_id": state["pid"], "symptoms": "ear pain"}).json()
    assert c["doctor"] == "dr_dlamini" and c["outcome"] == ""
    state["case"] = c["id"]


def test_only_the_doctor_who_owns_the_consultation_can_change_it(api):
    assert api("dr_nkosi").put(f"/consultations/{state['case']}/diagnosis", json={"diagnosis": "x", "treatment": "y"}).status_code == 403
    assert api("dr_nkosi").put(f"/consultations/{state['case']}/close").status_code == 403
    assert api("lab1").put(f"/consultations/{state['case']}/diagnosis", json={"diagnosis": "x"}).status_code == 403


def test_a_doctor_refers_to_a_specialty_and_the_load_is_shared(api):
    refs = [api("dr_dlamini").post("/referrals", json={"patient_id": state["pid"], "case_id": state["case"], "specialty": "ENT", "reason": f"ear {i}"}).json() for i in range(4)]
    assert {r["specialist"] for r in refs} == {"spec1", "spec_ent2"}  # both ENT specialists
    assert abs([r["specialist"] for r in refs].count("spec1") - [r["specialist"] for r in refs].count("spec_ent2")) <= 1
    assert all(r["doctor"] == "dr_dlamini" and r["status"] == "pending" for r in refs)
    state["refs"] = refs
    heart = api("dr_dlamini").post("/referrals", json={"patient_id": state["pid"], "case_id": state["case"], "specialty": "Cardiology", "reason": "murmur"}).json()
    assert heart["specialist"] == "spec_cardio"
    state["heart"] = heart


def test_a_specialty_nobody_has_is_refused(api):
    r = api("dr_dlamini").post("/referrals", json={"patient_id": state["pid"], "specialty": "Neurology", "reason": "x"})
    assert r.status_code == 409 and "Neurology" in r.json()["detail"]


def test_the_consultation_shows_it_was_referred(api):
    eventually(lambda: [c["outcome"] for c in api("dr_dlamini").get("/consultations", params={"patient_id": state["pid"]}).json() if c["id"] == state["case"]] == ["referred"])


def test_a_specialist_only_sees_their_own_referrals(api):
    mine = {r["id"] for r in api("spec1").get("/referrals").json()}
    theirs = {r["id"] for r in api("spec_ent2").get("/referrals").json()}
    assert mine and theirs and not (mine & theirs)
    assert state["heart"]["id"] not in mine | theirs
    assert [r["id"] for r in api("spec_cardio").get("/referrals").json()] == [state["heart"]["id"]]
    assert {r["id"] for r in api("dr_dlamini").get("/referrals").json()} >= mine | theirs  # the referring doctor sees all of theirs


def test_the_assigned_specialist_is_told_and_nobody_else(api):
    eventually(lambda: any("New referral to ENT" in n["text"] for n in api("spec1").get("/notifications").json()))
    assert not any("New referral" in n["text"] for n in api("spec_cardio").get("/notifications").json() if "ENT" in n["text"])


def test_only_the_assigned_specialist_answers_and_must_say_what_they_did(api):
    ref = state["refs"][0]; me, other = (("spec1", "spec_ent2") if ref["specialist"] == "spec1" else ("spec_ent2", "spec1"))
    body = {"report": "Fluid in the middle ear", "action": "recommended", "treatment": "Amoxicillin for 5 days"}
    assert api(other).put(f"/referrals/{ref['id']}/report", json=body).status_code == 403
    assert api("dr_dlamini").put(f"/referrals/{ref['id']}/report", json=body).status_code == 403  # doctors do not answer referrals
    assert api(me).put(f"/referrals/{ref['id']}/report", json={"report": "x"}).status_code == 422
    assert api(me).put(f"/referrals/{ref['id']}/report", json={**body, "action": "magic"}).status_code == 422
    assert api(me).put(f"/referrals/{ref['id']}/report", json={**body, "treatment": ""}).status_code == 422
    r = api(me).put(f"/referrals/{ref['id']}/report", json=body).json()
    assert r["status"] == "reported" and r["action"] == "recommended" and r["treatment"].startswith("Amoxicillin")


def test_the_doctor_hears_back_and_the_consultation_records_the_recommendation(api):
    eventually(lambda: any("Specialist report ready: ENT (recommended)" in n["text"] for n in api("dr_dlamini").get("/notifications").json()))
    eventually(lambda: [c["outcome"] for c in api("dr_dlamini").get("/consultations", params={"patient_id": state["pid"]}).json() if c["id"] == state["case"]] == ["treatment recommended"])
    assert not any("Specialist report ready" in n["text"] for n in api("dr_nkosi").get("/notifications").json())


def test_a_specialist_can_treat_the_patient_instead(api):
    ref = state["heart"]
    r = api("spec_cardio").put(f"/referrals/{ref['id']}/report", json={"report": "Innocent murmur", "action": "treated", "treatment": "Reassurance, no medication"}).json()
    assert r["action"] == "treated"
    eventually(lambda: [c["outcome"] for c in api("dr_dlamini").get("/consultations", params={"patient_id": state["pid"]}).json() if c["id"] == state["case"]] == ["treated by specialist"])


def test_the_doctor_then_treats_prescribes_and_closes(api):
    d = api("dr_dlamini")
    assert d.put(f"/consultations/{state['case']}/diagnosis", json={"diagnosis": "Otitis media", "treatment": "As the specialist recommended"}).json()["outcome"] == "treating"
    assert d.post("/prescriptions", json={"patient_id": state["pid"], "case_id": state["case"], "drug": "Amoxicillin", "dosage": "500 mg"}).status_code == 200
    assert d.put(f"/consultations/{state['case']}/close").json()["status"] == "closed"
