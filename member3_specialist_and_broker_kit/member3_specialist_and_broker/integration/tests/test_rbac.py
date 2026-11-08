import pytest

# (user, method, path, expected status). 403 = signed in but this role may not do this.
CASES = [
    ("dr_dlamini", "POST", "/patients", 403), ("dr_nkosi", "POST", "/patients", 403),  # only receptionists register patients
    ("pharm1", "GET", "/patients", 403), ("pharm1", "GET", "/lab/requests", 403), ("pharm1", "POST", "/consultations", 403),
    ("lab1", "GET", "/prescriptions", 403), ("lab1", "GET", "/patients", 403), ("lab1", "POST", "/lab/requests", 403),
    ("spec1", "GET", "/patients", 403), ("spec1", "PUT", "/lab/results/1", 403), ("spec1", "POST", "/appointments", 403),
    ("reception1", "POST", "/consultations", 403), ("reception1", "POST", "/prescriptions", 403), ("reception1", "POST", "/time-off", 403),
    ("reception1", "GET", "/api/patients/1/full-history", 403), ("reception1", "GET", "/api/cases/1/discharge.pdf", 403),
    ("reception1", "GET", "/audit", 403), ("reception1", "GET", "/api/staff", 403),
    ("dr_dlamini", "GET", "/audit", 403), ("dr_dlamini", "GET", "/users", 403), ("dr_dlamini", "PUT", "/lab/results/1", 403),
    ("dr_dlamini", "GET", "/api/staff", 403), ("dr_dlamini", "POST", "/api/staff", 403), ("dr_dlamini", "PUT", "/referrals/1/report", 403),
    ("pharm1", "POST", "/prescriptions", 403),  # prescriptions are written on the doctor's side only
    ("admin", "GET", "/patients", 403), ("admin", "GET", "/prescriptions", 403), ("admin", "GET", "/api/patients/1/full-history", 403),
    ("dr_dlamini", "GET", "/patients", 200), ("reception1", "GET", "/patients", 200), ("reception2", "GET", "/appointments", 200),
    ("lab1", "GET", "/lab/requests", 200), ("spec1", "GET", "/referrals", 200), ("pharm1", "GET", "/prescriptions", 200),
    ("admin", "GET", "/audit", 200), ("admin", "GET", "/api/staff", 200), ("admin", "GET", "/api/messaging", 200),
    ("dr_dlamini", "GET", "/staff", 200), ("pharm1", "GET", "/staff", 200), ("reception1", "GET", "/specialists", 200),
    ("dr_dlamini", "GET", "/nothing-here", 404),
]


@pytest.mark.parametrize("user,method,path,expected", CASES)
def test_role_matrix(api, user, method, path, expected):
    assert api(user).request(method, path).status_code == expected


def test_denied_requests_are_audited(api):
    assert any(r["status"] == 403 and r["user"] == "pharm1" and r["path"] == "/patients" for r in api("admin").get("/audit").json())
