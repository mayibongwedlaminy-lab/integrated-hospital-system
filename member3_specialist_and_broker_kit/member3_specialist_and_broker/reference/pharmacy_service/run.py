"""Run THIS service on its own, for development:   python run.py     (needs Node.js 22.13 or newer)

The pharmacy is written in Node.js (Express), not Python. This small launcher installs the two npm packages the first time and
then starts server.js, so every module in the project can be started the same way. The whole system is started by run.py at the top.
Calls to a service need the header  x-service-key: dev-key  (the gateway sends the real key)."""
import os, shutil, signal, subprocess, sys

here = os.path.dirname(os.path.abspath(__file__))
node, npm = shutil.which("node"), shutil.which("npm")
if not node:
    sys.exit("Node.js is not installed, so the pharmacy service cannot run. Install Node.js 22.13 or newer from https://nodejs.org")
version = subprocess.run([node, "-p", "process.versions.node"], capture_output=True, text=True).stdout.strip()
if tuple(int(x) for x in (version or "0.0").split(".")[:2]) < (22, 13):
    sys.exit(f"Node.js {version or '?'} is too old: the pharmacy service uses the built-in SQLite module, which needs Node.js 22.13 or newer.")
if not os.path.isdir(os.path.join(here, "node_modules", "express")):
    if not npm:
        sys.exit("npm was not found. Install Node.js (it includes npm), or run  npm install  inside pharmacy_service.")
    print("pharmacy: installing npm packages (first start only)...", flush=True)
    subprocess.check_call([npm, "install", "--no-audit", "--no-fund", "--loglevel=error"], cwd=here)
if "--prepare" in sys.argv:   # the project's start-up asks for this before launching anything
    sys.exit(0)
os.environ.setdefault("PPS_SERVICE_KEY", "dev-key")
child = subprocess.Popen([node, "--disable-warning=ExperimentalWarning", "server.js"], cwd=here)
signal.signal(signal.SIGTERM, lambda *_: (child.terminate(), sys.exit(0)))  # stopping this wrapper must stop node too
try:
    sys.exit(child.wait())
except KeyboardInterrupt:
    child.terminate()
