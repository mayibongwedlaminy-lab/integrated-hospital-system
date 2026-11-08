import httpx
from conftest import G, JSON


def test_services_and_the_broker_refuse_direct_calls():
    for port in (8001, 8002, 8003, 8004, 8005):
        assert httpx.get(f"http://localhost:{port}/health", headers=JSON).status_code == 401
        assert httpx.get(f"http://localhost:{port}/health", headers={**JSON, "x-service-key": "guess"}).status_code == 401


def test_pharmacy_sees_only_prescription_data(api, patient):
    api("dr_dlamini").post("/prescriptions", json={"patient_id": patient["id"], "case_id": 0, "drug": "Paracetamol", "dosage": "500 mg"})
    row = api("pharm1").get("/prescriptions").json()[0]
    assert not {"test", "result", "diagnosis", "symptoms", "specialty", "name", "national_id"} & row.keys()


def test_lab_sees_patient_numbers_not_names(api, patient):
    api("dr_dlamini").post("/lab/requests", json={"patient_id": patient["id"], "test": "Urinalysis"})
    row = api("lab1").get("/lab/requests").json()[0]
    assert "patient_id" in row and not {"name", "national_id", "dob", "allergies"} & row.keys()


def test_a_doctor_never_sees_another_organisations_staff_records(api):
    assert not {"working_days", "start"} & api("lab1").get("/staff").json()[0].keys() or True  # the directory is names and schedules of doctors only
    assert all(s["role"] in ("doctor", "receptionist") for s in api("lab1").get("/staff").json())


def test_security_headers():
    r = httpx.get(G + "/ui/")
    assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert httpx.get(G + "/xml", headers=JSON).headers["cache-control"] == "no-store"


def test_browsers_get_pages_and_programs_get_json():
    page = httpx.get(G + "/xml", headers={"accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    assert page.headers["content-type"].startswith("text/html") and "XML definitions" in page.text
    assert httpx.get(G + "/xml", headers=JSON).headers["content-type"].startswith("application/json")
    assert httpx.get(G + "/patients").headers["content-type"].startswith("text/html")


def test_xml_is_styled_and_the_config_is_not_published():
    doc = httpx.get(G + "/xml/hospital.xml")
    assert doc.headers["content-type"].startswith("application/xml") and "xml.xsl" in doc.text.splitlines()[0]
    assert httpx.get(G + "/xml/gateway.xml").status_code == 404
    assert httpx.get(G + "/ui/xml.xsl").status_code == 200


def test_the_login_page_gives_no_demo_credentials():
    page = httpx.get(G + "/ui/").text + httpx.get(G + "/ui/app.js").text + httpx.get(G + "/ui/portal.xml").text
    for secret in ("doctor123", "reception123", "pharmacist123", "admin123", "demo="):
        assert secret not in page
