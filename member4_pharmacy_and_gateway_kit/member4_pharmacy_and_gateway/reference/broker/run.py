"""Run only the broker, for development:   python run.py
Calls need the headers  x-service-key: dev-key  and  x-client: <who you are, as named in broker.xml>."""
import os, subprocess, sys

here = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("PPS_SERVICE_KEY", "dev-key")
sys.exit(subprocess.call([sys.executable, os.path.join(here, "broker.py")]))
