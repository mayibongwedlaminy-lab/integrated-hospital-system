"""Starts the real system (broker, four services, gateway, and the Java analyzer when Java is there) in a temporary folder.
Nothing is pre-loaded: the tests sign in as the starting administrator and create every account through the admin API."""
import secrets, socket, sqlite3, sys, time
from datetime import date, timedelta
from pathlib import Path
import httpx, pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "integration"))
import system as sysmod  # noqa: E402

G, JSON, SERVICES = sysmod.G, {"accept": "application/json"}, sysmod.SERVICES
PASSWORD, ADMIN_PASSWORD = "test-pass-1", "admin123"
ALL_WEEK = "Mon,Tue,Wed,Thu,Fri,Sat,Sun"
STAFF = [  # who the tests create (the administrator does this in the portal)
    dict(username="reception1", role="receptionist", full_name="Nomvula Dube"),
    dict(username="reception2", role="receptionist", full_name="Sibusiso Maseko"),
    dict(username="dr_dlamini", role="doctor", full_name="Dr. Sipho Dlamini", specialty="General Practice", working_days="Mon,Tue,Wed,Thu,Fri", start="08:00", end="16:00", slot_minutes="30"),
    dict(username="dr_nkosi", role="doctor", full_name="Dr. Lindiwe Nkosi", specialty="General Practice", working_days="Mon,Tue,Wed", start="10:00", end="18:00", slot_minutes="30"),
    dict(username="dr_mamba", role="doctor", full_name="Dr. Mandla Mamba", specialty="General Practice", working_days="Thu,Fri,Sat", start="08:00", end="14:00", slot_minutes="30"),
    dict(username="lab1", role="lab_technician", full_name="Thabo Gamedze"),
    dict(username="lab2", role="lab_technician", full_name="Zodwa Simelane"),
    dict(username="spec1", role="specialist", full_name="Dr. Nokuthula Ginindza", specialty="ENT"),
    dict(username="spec_ent2", role="specialist", full_name="Dr. Ayanda Magagula", specialty="ENT"),
    dict(username="spec_cardio", role="specialist", full_name="Dr. Bheki Hlophe", specialty="Cardiology"),
    dict(username="pharm1", role="pharmacist", full_name="Mpho Shongwe"),
    dict(username="pharm2", role="pharmacist", full_name="Nelisiwe Zwane"),
]


def first_monday(on_or_after):
    d = on_or_after
    return d + timedelta(days=(7 - d.weekday()) % 7)


MONDAY = first_monday(date(2031, 1, 6))  # a far-future Monday, so tests never depend on today's date


def eventually(check, timeout=25, interval=0.4):
    """Messages arrive a moment later: keep asking until `check()` returns something truthy."""
    end = time.time() + timeout
    while True:
        try:
            value = check()
            if value:
                return value
        except Exception:  # noqa: BLE001  not ready yet (a service may still be starting)
            pass
        if time.time() > end:
            raise AssertionError(f"this did not happen within {timeout} seconds")
        time.sleep(interval)


class System:
    def __init__(self, data, key):
        self.data, self.key, self.procs, self.mods = data, key, {}, sysmod.locate(ROOT)
        self.env = sysmod.make_env(self.mods, key, data)

    def stop_one(self, name):
        sysmod.terminate(self.procs[name])
        self.procs[name].wait(5)

    def restart(self, name):
        self.procs[name] = sysmod.start_one(name, self.mods, self.env, ROOT)
        assert sysmod.wait_ready(self.key, 40), f"{name} did not come back"

    def start(self):
        self.procs, self.mods = sysmod.start(self.data, self.key, ROOT)
        if not sysmod.wait_ready(self.key):
            raise RuntimeError("the system did not start in 30 seconds")

    def stop(self):
        sysmod.stop(self.procs)

    def login(self, user, password=None):
        return httpx.post(G + "/auth/login", json={"username": user, "password": password or (ADMIN_PASSWORD if user == "admin" else PASSWORD)})

    def client(self, user, password=None):
        token = self.login(user, password).json()["token"]
        return httpx.Client(base_url=G, headers={**JSON, "authorization": "Bearer " + token}, timeout=15)

    def clear_lockouts(self):
        with sqlite3.connect(self.data / "gateway.db") as c:
            c.execute("DELETE FROM attempts")


@pytest.fixture(scope="session")
def system_fx(tmp_path_factory):
    for port in (8000, *SERVICES.values(), sysmod.BROKER_PORT):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                pytest.exit(f"Port {port} is already in use. Stop the running system before running the tests.", 2)
    s = System(tmp_path_factory.mktemp("pps"), secrets.token_hex(16))
    s.start()
    admin = s.client("admin")  # the starting account: the only one that exists
    for person in STAFF:
        r = admin.post("/api/staff", json={**person, "password": PASSWORD})
        assert r.status_code == 200, (person["username"], r.text)
    yield s
    s.stop()


@pytest.fixture(scope="session")
def api(system_fx):
    """A signed-in client per user name: api("dr_dlamini")."""
    cache = {}
    return lambda user: cache.setdefault(user, system_fx.client(user))


@pytest.fixture(scope="session")
def system(system_fx):
    return system_fx


@pytest.fixture(scope="session")
def patient(api):
    """One registered patient for tests that just need somebody (registered the proper way: by a receptionist)."""
    return api("reception1").post("/patients", json={"national_id": "9000000001", "name": "Shared Patient", "dob": "1990-01-01"}).json()
