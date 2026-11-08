"""Starts the system from module folders. Shared by run.py, check.py and the tests.

A module is taken from  <project>/<name>  when you have it, otherwise from  <project>/reference/<name>.
That is how one person's module is swapped into a complete working system."""
import json, os, shutil, signal, subprocess, sys, time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parent.parent
SERVICES = {"hospital_service": 8001, "lab_service": 8002, "specialist_service": 8003, "pharmacy_service": 8004}
BROKER_PORT = 8005
MODULES = [*SERVICES, "broker", "analyzer", "gateway", "client"]
CONTRACTS = {"hospital_service": "hospital", "lab_service": "laboratory", "specialist_service": "specialist",
             "pharmacy_service": "pharmacy", "broker": "broker", "analyzer": "analyzer", "gateway": "gateway"}
G = "http://localhost:8000"


def locate(root=ROOT):
    found = {}
    for name in MODULES:
        for base in (Path(root), Path(root) / "reference"):
            if (base / name).is_dir():
                found[name] = base / name
                break
        else:
            raise SystemExit(f"Module '{name}' was not found in {root} or {Path(root) / 'reference'}.")
    return found


def make_env(mods, key, data_dir=None):
    env = {**os.environ, "PPS_SERVICE_KEY": key, "PPS_MODULE_DIRS": json.dumps({k: str(v) for k, v in mods.items()})}
    if data_dir:
        env["PPS_DATA"] = str(data_dir)
    return env


def is_native(path):
    """A module written in another language (Node.js, Java...) says so in module.json and starts through its own run.py."""
    return (Path(path) / "module.json").exists()


def language(path):
    """What a module is written in, for the start-up list."""
    try:
        return json.loads((Path(path) / "module.json").read_text(encoding="utf-8")).get("language", "native")
    except (OSError, ValueError):
        pass
    if Path(path).name == "client":
        return "JavaScript / HTML / XSL"
    if Path(path).name == "analyzer":
        return "Java (JDK only)"
    return "Python (FastAPI)"


def command(name, mods):
    if is_native(mods[name]):
        return [sys.executable, str(mods[name] / "run.py")]
    if name == "broker":
        return [sys.executable, str(mods["broker"] / "broker.py")]
    if name == "gateway":
        return [sys.executable, str(mods["gateway"] / "gateway.py")]
    if name == "analyzer":
        return [sys.executable, str(mods["analyzer"] / "run.py")]
    return [sys.executable, str(mods[name] / "engine" / "service.py"), str(mods[name] / "service.xml")]


def start_one(name, mods, env, root=ROOT):
    # its own process group on Linux/macOS, so stop() reaches children too (the analyzer's run.py starts java)
    return subprocess.Popen(command(name, mods), cwd=root, env=env, **({"start_new_session": True} if os.name == "posix" else {}))


def analyzer_wanted():
    """The Java analyzer runs when Java is installed (set PPS_ANALYZER=0 to leave it out)."""
    return shutil.which("java") is not None and os.environ.get("PPS_ANALYZER", "1") != "0"


def prepare(mods, env):
    """Install or compile what a module in another language needs (npm packages, Java classes) BEFORE the clock for start-up begins."""
    for name, path in mods.items():
        if is_native(path):
            subprocess.check_call([sys.executable, str(path / "run.py"), "--prepare"], env=env, cwd=path)


def start(data_dir, key, root=ROOT):
    """Start the broker, the four services, the gateway (and the analyzer if Java is there). Returns (processes by name, module folders)."""
    mods = locate(root)
    env = make_env(mods, key, data_dir)
    prepare(mods, env)
    names = ["broker", *SERVICES, "gateway", *(["analyzer"] if analyzer_wanted() else [])]
    return {n: start_one(n, mods, env, root) for n in names}, mods


def wait_ready(key, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if httpx.get(G + "/xml").status_code == 200 and all(
                    httpx.get(f"http://localhost:{p}/health", headers={"x-service-key": key}).status_code == 200
                    for p in (*SERVICES.values(), BROKER_PORT)):
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    return False


def terminate(p):
    try:
        if os.name == "posix":
            os.killpg(p.pid, signal.SIGTERM)
        else:
            p.terminate()
    except (ProcessLookupError, PermissionError):
        pass


def stop(procs):
    for p in procs.values():
        terminate(p)
    for p in procs.values():
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
