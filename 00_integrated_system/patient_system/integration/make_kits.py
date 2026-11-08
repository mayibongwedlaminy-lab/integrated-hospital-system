"""TEAM LEAD ONLY. Build one kit per member plus the integrated system:   python integration/make_kits.py [output_folder] [--per-module]

A kit holds the member's own module, a complete working copy of everyone else's in reference/, the contracts,
the checks, and the guides. Members work in their own folder and hand back only that folder."""
import shutil, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import system  # noqa: E402

MEMBERS = [("member1_hospital_and_portal", ["hospital_service", "client"], "Member 1: hospital service and client portal"),
           ("member2_lab_and_java_analyzer", ["lab_service", "analyzer"], "Member 2: laboratory service (Java) and Java analyzer"),
           ("member3_specialist_and_broker", ["specialist_service", "broker"], "Member 3: specialist service and message broker"),
           ("member4_pharmacy_and_gateway", ["pharmacy_service", "gateway"], "Member 4: pharmacy service (Node.js) and gateway (Python)")]
SKIP = shutil.ignore_patterns("*.db", "*.db-wal", "*.db-shm", "__pycache__", ".pytest_cache", "*.pyc", "reference", "node_modules", "*.zip", "build", "lab.json", "lab.json.tmp")
SHARED_FILES = ["run.py", "check.py", "TEAM_GUIDE.md", "README.md", "requirements.txt", "requirements-dev.txt", "pytest.ini", ".gitignore"]

START = """# {title}

You build: {mine}.
Everything else is in `reference/`: a complete, working copy of the other members' modules, so you can always run the whole system with your changes in it.

1. `pip install -r requirements.txt`
2. Read `TEAM_GUIDE.md`, `docs/INTEGRATION.md`, then the README inside each of your folders.
3. Work **only inside your own folders**: {folders}.
4. See your work in the whole system: `python run.py`, then open http://localhost:8000/ui/
5. Before handing over: `python check.py`. It must end with **READY TO HAND OVER**.
6. Send back a zip of **your folders only** ({folders}).
"""


def kit(out, folder, modules, title):
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / folder
        for module in modules:
            shutil.copytree(ROOT / module, stage / module, ignore=SKIP)
        for m in system.MODULES:
            shutil.copytree(ROOT / m, stage / "reference" / m, ignore=SKIP)
        for d in ("contracts", "integration", "tools", "docs"):
            shutil.copytree(ROOT / d, stage / d, ignore=SKIP)
        (stage / "integration" / "make_kits.py").unlink()
        for f in SHARED_FILES:
            shutil.copy(ROOT / f, stage / f)
        (stage / "START_HERE.md").write_text(START.format(
            title=title, mine=" and ".join(f"**{m}/**" for m in modules), folders=", ".join(f"`{m}/`" for m in modules)), encoding="utf-8")
        shutil.make_archive(str(out / f"{folder}_kit"), "zip", tmp, folder)


def main(out):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    for folder, modules, title in MEMBERS:
        kit(out, folder, modules, title)
    if "--per-module" in sys.argv:  # one kit per module instead (for a different team size)
        for m in system.MODULES:
            kit(out, f"module_{m}", [m], f"Module: {m}")
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copytree(ROOT, Path(tmp) / "patient_system", ignore=SKIP)
        shutil.make_archive(str(out / "00_integrated_system"), "zip", tmp, "patient_system")
    print("built:", ", ".join(sorted(p.name for p in out.glob("*.zip"))))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ROOT / "kits")
