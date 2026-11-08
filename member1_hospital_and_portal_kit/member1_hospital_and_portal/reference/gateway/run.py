"""Run only the gateway, for development:   python run.py
It needs the four services (and the client folder) to be useful: use run.py at the top of the project to start everything
with your gateway in it."""
import os, subprocess, sys

here = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("PPS_SERVICE_KEY", "dev-key")
sys.exit(subprocess.call([sys.executable, os.path.join(here, "gateway.py")]))
