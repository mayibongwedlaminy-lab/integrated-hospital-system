"""Run THIS service on its own, for development:   python run.py

Anything that calls another organisation (a "peer") answers 503 unless that peer is running too.
To run the whole system with your module in it, use run.py at the top of the project.
Calls to a service need the header  x-service-key: dev-key  (the gateway sends the real key)."""
import os, subprocess, sys

here = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("PPS_SERVICE_KEY", "dev-key")
print("Service starting. Docs: nothing to open in a browser without the key; send  x-service-key: dev-key", flush=True)
sys.exit(subprocess.call([sys.executable, os.path.join(here, "engine", "service.py"), os.path.join(here, "service.xml")]))
