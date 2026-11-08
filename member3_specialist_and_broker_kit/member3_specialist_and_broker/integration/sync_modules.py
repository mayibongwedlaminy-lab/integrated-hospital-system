"""TEAM LEAD ONLY. Copy the team's engine and contracts into every module:   python integration/sync_modules.py

The engine lives once, in integration/engine_src, and is copied into each module's engine/ folder so every module runs on
its own. Run this after changing integration/engine_src, client/app.css or anything in contracts/."""
import shutil, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import system


def sync(root=system.ROOT):
    root, mods, src = Path(root), system.locate(root), Path(root) / "integration" / "engine_src"
    css = mods["client"] / "app.css"
    for name in system.SERVICES:
        for f in ("service.py", "pages.py", "messaging.py", "VERSION"):
            (mods[name] / "engine").mkdir(exist_ok=True)
            shutil.copy(src / f, mods[name] / "engine" / f)
        shutil.copy(css, mods[name] / "engine" / "app.css")
    (mods["gateway"] / "engine").mkdir(exist_ok=True)
    for f in ("pages.py", "report.py", "messaging.py", "VERSION"):
        shutil.copy(src / f, mods["gateway"] / "engine" / f)
    shutil.copy(css, mods["gateway"] / "engine" / "app.css")
    (mods["broker"] / "engine").mkdir(exist_ok=True)
    for f in ("pages.py", "VERSION"):
        shutil.copy(src / f, mods["broker"] / "engine" / f)
    shutil.copy(css, mods["broker"] / "engine" / "app.css")
    for name, contract in system.CONTRACTS.items():
        shutil.copy(root / "contracts" / f"{contract}.contract.xml", mods[name] / "contract.xml")
    print("engine and contracts copied into", ", ".join(system.CONTRACTS))


if __name__ == "__main__":
    sync()
