"""Is my module ready to hand over?   python check.py

  1. the shared engine and contracts are the team's versions
  2. the portal only uses routes the gateway offers
  3. the system starts with YOUR module(s) swapped in, and each of your modules passes its contract

In a team kit, "your modules" are the folders next to this file; everything else comes from reference/."""
import secrets, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "integration"), str(ROOT / "contracts")]
import check_contract, check_modules, check_portal, system  # noqa: E402


def main():
    mods = system.locate(ROOT)
    mine = [n for n, p in mods.items() if p.parent == ROOT]
    print("Your modules:", ", ".join(mine) or "none"); bad = 0

    print("\n1. Shared pieces in sync?")
    problems = check_modules.check(ROOT)
    print("\n".join("  [FAIL] " + p for p in problems) or "  [ ok ] engine, stylesheet and contracts match the team's versions"); bad += len(problems)

    print("\n2. Portal and gateway agree?")
    problems = check_portal.check(mods["gateway"] / "gateway.xml", mods["client"] / "portal.xml")
    print("\n".join("  [FAIL] " + p for p in problems) or "  [ ok ] every list, form and button uses a route its role may use"); bad += len(problems)

    to_check = [n for n in mine if n in system.CONTRACTS]
    if "analyzer" in to_check and not system.analyzer_wanted():
        print("\n(The analyzer contract needs Java, which is not installed here, so it is skipped.)")
        to_check.remove("analyzer")
    if not to_check:
        print("\n3. Contracts: nothing to run for the client. Run the browser tests with:  pytest integration/tests/test_ui.py")
    else:
        print("\n3. Contracts (starting the system with your module in it)")
        key = secrets.token_hex(8)
        with tempfile.TemporaryDirectory() as data:
            procs, _ = system.start(data, key, ROOT)
            try:
                if not system.wait_ready(key):
                    print("  [FAIL] the system did not start. Read the error above: your module may have a broken XML or Python file."); bad += 1
                else:
                    for n in to_check:
                        bad += check_contract.run_contract(ROOT / "contracts" / f"{system.CONTRACTS[n]}.contract.xml", key)[1]
            finally:
                system.stop(procs)
    print("\n" + ("READY TO HAND OVER: all checks passed." if not bad else f"NOT READY: {bad} problem(s) above."))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
