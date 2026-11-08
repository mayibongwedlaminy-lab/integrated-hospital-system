"""Signing in, creating accounts, passwords, deactivation, lockout. Nothing is pre-loaded: only the starting administrator exists."""
import re
import httpx
from conftest import ADMIN_PASSWORD, G, JSON, PASSWORD, ROOT
import conftest


def test_the_only_starting_account_is_the_administrator():
    xml = (conftest.sysmod.locate(ROOT)["gateway"] / "gateway.xml").read_text()
    assert len(re.findall(r"<user ", xml)) == 1 and 'role="administrator"' in xml
    assert "password=" not in xml and "secret=" not in xml
    assert re.findall(r'hash="[0-9a-f]{64}"', xml), "expected a PBKDF2 hash"


def test_the_starting_administrator_must_choose_a_new_password(system):
    r = system.login("admin", ADMIN_PASSWORD)
    assert r.status_code == 200 and r.json()["must_change"] is True and r.json()["name"] == "System Administrator"


def test_no_demo_accounts_exist():
    for name in ("demo", "doctor", "reception", "reception_demo", "pharmacist"):
        assert httpx.post(G + "/auth/login", json={"username": name, "password": "doctor123"}).status_code == 401


def test_no_token_is_refused():
    assert httpx.get(G + "/patients", headers=JSON).status_code == 401
    assert httpx.get(G + "/patients", headers={**JSON, "authorization": "Bearer nonsense"}).status_code == 401


def test_wrong_password_and_unknown_user_look_the_same():
    a = httpx.post(G + "/auth/login", json={"username": "dr_dlamini", "password": "nope"})
    b = httpx.post(G + "/auth/login", json={"username": "nobody", "password": "nope"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_the_administrator_creates_an_account_that_can_sign_in(api, system):
    r = api("admin").post("/api/staff", json={"username": "new.nurse", "role": "receptionist", "full_name": "Nurse New", "password": "starting-pass"})
    assert r.status_code == 200 and r.json()["created"] is True
    login = system.login("new.nurse", "starting-pass").json()
    assert login["name"] == "Nurse New" and login["role"] == "receptionist" and login["must_change"] is True


def test_account_rules(api):
    admin = api("admin")
    assert api("dr_dlamini").post("/api/staff", json={"username": "x_sneaky", "role": "pharmacist", "full_name": "S", "password": "long-enough-1"}).status_code == 403
    assert admin.post("/api/staff", json={"username": "x_short", "role": "pharmacist", "full_name": "S", "password": "abc"}).status_code == 422
    assert admin.post("/api/staff", json={"username": "Bad Name", "role": "pharmacist", "full_name": "S", "password": "long-enough-1"}).status_code == 422
    assert admin.post("/api/staff", json={"username": "x_norole", "role": "wizard", "full_name": "S", "password": "long-enough-1"}).status_code == 422
    assert admin.post("/api/staff", json={"username": "dr_dlamini", "role": "pharmacist", "full_name": "Clash"}).status_code == 409
    assert admin.post("/api/staff", json={"username": "x_nameless", "role": "pharmacist", "password": "long-enough-1"}).status_code == 422


def test_several_people_can_hold_the_same_role(api):
    staff = api("admin").get("/api/staff").json()
    for role, at_least in [("doctor", 3), ("receptionist", 2), ("lab_technician", 2), ("specialist", 3), ("pharmacist", 2)]:
        assert sum(1 for s in staff if s["role"] == role) >= at_least, role
    doctor = next(s for s in staff if s["username"] == "dr_nkosi")
    assert doctor["schedule"] == "Mon,Tue,Wed 10:00-18:00" and doctor["full_name"] == "Dr. Lindiwe Nkosi"


def test_people_directory_gives_names_to_everyone(api):
    names = {p["username"]: p["full_name"] for p in api("lab1").get("/api/people").json()}
    assert names["dr_dlamini"] == "Dr. Sipho Dlamini"


def test_a_person_changes_their_own_password(api, system):
    api("admin").post("/api/staff", json={"username": "pw_user", "role": "pharmacist", "full_name": "Password User", "password": "first-pass-1"})
    me = system.client("pw_user", "first-pass-1")
    assert me.post("/api/password", json={"current_password": "wrong", "new_password": "second-pass-2"}).status_code == 401
    assert me.post("/api/password", json={"current_password": "first-pass-1", "new_password": "short"}).status_code == 422
    assert me.post("/api/password", json={"current_password": "first-pass-1", "new_password": "first-pass-1"}).status_code == 422
    assert me.post("/api/password", json={"current_password": "first-pass-1", "new_password": "second-pass-2"}).status_code == 200
    assert system.login("pw_user", "first-pass-1").status_code == 401
    ok = system.login("pw_user", "second-pass-2")
    assert ok.status_code == 200 and ok.json()["must_change"] is False


def test_an_administrator_reset_makes_the_person_choose_again(api, system):
    api("admin").put("/api/staff/pw_user", json={"password": "reset-by-admin-1"})
    assert system.login("pw_user", "reset-by-admin-1").json()["must_change"] is True


def test_deactivating_an_account_stops_it_at_once(api, system):
    api("admin").post("/api/staff", json={"username": "leaver", "role": "receptionist", "full_name": "Soon Gone", "password": "leaver-pass-1"})
    me = system.client("leaver", "leaver-pass-1")
    assert me.get("/patients").status_code == 200
    assert api("admin").put("/api/staff/leaver", json={"active": "no"}).status_code == 200
    assert me.get("/patients").status_code == 401  # the token it already holds no longer works
    assert system.login("leaver", "leaver-pass-1").status_code == 401
    assert api("admin").put("/api/staff/leaver", json={"active": "yes"}).status_code == 200
    assert system.login("leaver", "leaver-pass-1").status_code == 200


def test_an_administrator_cannot_lock_themselves_out(api):
    assert api("admin").put("/api/staff/admin", json={"active": "no"}).status_code == 409


def test_lockout_after_repeated_failures(system, api):
    api("admin").post("/api/staff", json={"username": "lock_me", "role": "receptionist", "full_name": "Lock Me", "password": "lock-pass-123"})
    codes = [httpx.post(G + "/auth/login", json={"username": "lock_me", "password": "bad"}).status_code for _ in range(5)]
    assert codes == [401] * 5
    assert system.login("lock_me", "lock-pass-123").status_code == 429  # even the right password is refused while locked
    assert system.login("lab2").status_code == 200  # other people are unaffected
    system.clear_lockouts()
    assert system.login("lock_me", "lock-pass-123").status_code == 200


def test_sign_ins_and_failures_are_audited(api):
    log = api("admin").get("/audit").json()
    assert {200, 401, 429} <= {r["status"] for r in log if r["path"] == "/auth/login"}
    assert any(r["path"] == "/api/staff" and r["method"] == "POST" for r in log)
