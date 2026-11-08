"""Are the shared pieces in sync across modules?   python integration/check_modules.py

Every Python service must run the team's engine unchanged (a module in another language, marked by module.json, is exempt), every module must hold the agreed contract, and the stylesheet copies
must match client/app.css. Differences are listed; the team lead fixes them with  python integration/sync_modules.py."""
import hashlib, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import system


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:10] if Path(path).exists() else None


def check(root=system.ROOT):
    root, mods = Path(root), system.locate(root)
    src, css, problems = root / "integration" / "engine_src", mods["client"] / "app.css", []
    expected = {name: {"service.py": src / "service.py", "pages.py": src / "pages.py", "messaging.py": src / "messaging.py", "VERSION": src / "VERSION", "app.css": css}
                for name in system.SERVICES}
    expected["gateway"] = {"pages.py": src / "pages.py", "report.py": src / "report.py", "messaging.py": src / "messaging.py", "VERSION": src / "VERSION", "app.css": css}
    expected["broker"] = {"pages.py": src / "pages.py", "VERSION": src / "VERSION", "app.css": css}
    for name, files in expected.items():
        if system.is_native(mods[name]):  # written in another language: it has no Python engine, only the contract to keep
            for needed in ("module.json", "run.py", "service.xml"):
                if not (mods[name] / needed).exists():
                    problems.append(f"{name}/{needed} is missing (a module in another language needs it)")
            continue
        for f, canon in files.items():
            if sha(mods[name] / "engine" / f) != sha(canon):
                problems.append(f"{name}/engine/{f} is not the team's version (do not edit engine/; ask the team lead to sync)")
    for name, contract in system.CONTRACTS.items():
        if sha(mods[name] / "contract.xml") != sha(root / "contracts" / f"{contract}.contract.xml"):
            problems.append(f"{name}/contract.xml differs from contracts/{contract}.contract.xml (the agreed interface)")
    return problems


if __name__ == "__main__":
    found = check()
    print("\n".join(found) or "all modules use the team's engine and contracts")
    sys.exit(1 if found else 0)
