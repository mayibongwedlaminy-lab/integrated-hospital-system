"""The Java lab analyzer: a separate system that joins only through the broker. Skipped when Java is not installed."""
import shutil, time
import httpx
import pytest
from conftest import eventually

pytestmark = pytest.mark.skipif(shutil.which("java") is None, reason="Java is not installed")


def test_automated_test_is_completed_by_the_java_analyzer(api):
    api("dr_dlamini").post("/lab/requests", json={"patient_id": 7001, "test": "Blood glucose"})
    done = eventually(lambda: [x for x in api("lab1").get("/lab/requests", params={"patient_id": 7001}).json() if x["status"] == "completed"], timeout=40)
    assert "mmol/L" in done[0]["result"] and done[0]["technician"] == "analyzer"
    eventually(lambda: any("Lab result ready: Blood glucose" in n["text"] for n in api("dr_dlamini").get("/notifications").json()))


def test_malaria_test_gets_a_result_too(api):
    api("dr_dlamini").post("/lab/requests", json={"patient_id": 7002, "test": "Malaria rapid test"})
    done = eventually(lambda: [x for x in api("lab1").get("/lab/requests", params={"patient_id": 7002}).json() if x["status"] == "completed"], timeout=40)
    assert done[0]["result"] in ("negative", "positive")


def test_tests_without_a_machine_stay_for_the_technician(api):
    api("dr_dlamini").post("/lab/requests", json={"patient_id": 7003, "test": "Full blood count"})
    time.sleep(4)
    assert [r["status"] for r in api("lab1").get("/lab/requests", params={"patient_id": 7003}).json()] == ["pending"]


def test_an_order_the_analyzer_cannot_run_is_dead_lettered(api, system):
    httpx.post("http://localhost:8005/send", headers={"x-service-key": system.key, "x-client": "lab", "accept": "application/json"},
               json={"destination": "lab.analyzer.orders", "body": {"id": 1, "test": "Moon rock assay"}, "correlation_id": "1"})
    eventually(lambda: {r["id"]: r for r in api("admin").get("/api/messaging").json()}["lab.analyzer.orders"]["dead"] >= 1, timeout=40)
