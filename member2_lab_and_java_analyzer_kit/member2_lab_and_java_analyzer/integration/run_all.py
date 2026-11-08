"""Start the whole system from the module folders:   python run.py

Your own module folders are used when present; anything missing comes from reference/.
Environment: PPS_DATA (database folder), PPS_HOST (gateway address), PPS_SECRET (fixed token secret),
PPS_ANALYZER=0 (do not start the Java analyzer). The service key is made fresh on every start.
The system starts empty: sign in as "admin" and add everyone else in the portal."""
import os, secrets, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import system


def main():
    key = os.environ.setdefault("PPS_SERVICE_KEY", secrets.token_hex(24))
    procs, mods = system.start(None, key)
    print("Modules in use:")
    for name, path in mods.items():
        print(f"  {name:20} {system.language(path):34} {'reference/ (not yours)' if 'reference' in path.parts else 'your folder'}")
    if not system.wait_ready(key):
        print("The system did not start within 30 seconds. Look for an error message above.", flush=True)
    else:
        print("Sign in as  admin  (the starting password is in the README); you will be asked to choose a new one.", flush=True)
    print("Open http://localhost:8000/ui/   (Ctrl+C to stop)", flush=True)
    try:
        for p in procs.values():
            p.wait()
    except KeyboardInterrupt:
        system.stop(procs)


if __name__ == "__main__":
    main()
