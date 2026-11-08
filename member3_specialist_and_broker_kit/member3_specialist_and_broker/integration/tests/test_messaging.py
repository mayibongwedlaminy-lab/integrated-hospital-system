"""The message broker as the other components see it: who may do what, dead letters, and that a bad message blocks nothing."""
import httpx
from conftest import eventually

B = "http://localhost:8005"


def broker(system, client, path, body=None, method="POST"):
    return httpx.request(method, B + path, json=body, timeout=30, headers={"x-service-key": system.key, "x-client": client, "accept": "application/json"})


def test_only_the_administrator_sees_the_queues(api):
    assert api("dr_dlamini").get("/api/messaging").status_code == 403
    rows = {r["id"]: r for r in api("admin").get("/api/messaging").json()}
    assert {"lab.requests", "specialist.referrals", "hospital.case-closed", "hospital.case-updates", "lab.analyzer.orders", "lab.analyzer.results",
            "events:gateway-notifications"} <= set(rows)
    assert {"ready", "inflight", "dead", "who_sends", "who_receives"} <= set(rows["hospital.case-closed"])


def test_a_component_may_only_use_its_own_destinations(system):
    assert broker(system, "lab", "/send", {"destination": "hospital.case-closed", "body": {}}).status_code == 403
    assert broker(system, "hospital", "/receive", {"destination": "lab.requests", "wait": 0}).status_code == 403
    assert broker(system, "pharmacy", "/admin/destinations", method="GET").status_code == 403
    assert httpx.get(B + "/admin/destinations").status_code == 401


def test_a_message_that_can_never_succeed_goes_to_the_dead_letters_and_blocks_nothing(api, system, patient):
    case = api("dr_dlamini").post("/consultations", json={"patient_id": patient["id"], "symptoms": "x"}).json()["id"]
    dead = lambda: {r["id"]: r for r in api("admin").get("/api/messaging").json()}["hospital.case-closed"]["dead"]
    before = dead()
    broker(system, "pharmacy", "/send", {"destination": "hospital.case-closed", "body": {"case_id": 987654, "status": "closed"}})  # no such case
    broker(system, "pharmacy", "/send", {"destination": "hospital.case-closed", "body": {"case_id": case, "status": "closed"}})  # a good one behind it
    eventually(lambda: [c["status"] for c in api("dr_dlamini").get("/consultations", params={"patient_id": patient["id"]}).json() if c["id"] == case] == ["closed"])
    eventually(lambda: dead() == before + 1)
    reasons = broker(system, "gateway", "/admin/messages?destination=hospital.case-closed&state=dead", method="GET").json()
    assert any("404" in (m["reason"] or "") for m in reasons)


def test_the_administrator_can_put_dead_letters_back(api):
    r = api("admin").post("/api/messaging/hospital.case-closed/retry")
    assert r.status_code == 200 and r.json()["retried"] >= 1
    assert api("dr_dlamini").post("/api/messaging/x/retry").status_code == 403


def test_referrals_are_delivered_by_queue_too(api, system, patient):
    # a message put on the specialist's queue is handled exactly like a normal POST /referrals (including choosing the specialist)
    broker(system, "gateway", "/send", {"destination": "specialist.referrals", "headers": {"user": "dr_nkosi", "role": "doctor"},
                                        "body": {"patient_id": patient["id"], "specialty": "ENT", "reason": "queued"}})
    found = eventually(lambda: [r for r in api("dr_nkosi").get("/referrals", params={"patient_id": patient["id"]}).json() if r["reason"] == "queued"])
    assert len(found) == 1 and found[0]["status"] == "pending" and found[0]["doctor"] == "dr_nkosi" and found[0]["specialist"] in ("spec1", "spec_ent2")
