"""Check a RUNNING service (or the gateway) against its contract.

    python contracts/check_contract.py contracts/laboratory.contract.xml [--key dev-key]

The contract says which port to talk to, so start the service first (python run.py inside its folder).
Peers named in a contract (<peer>) must be running as well. Exit code 0 = every step passed.
`python check.py` at the top of the project does all of this for you.

Step attributes: method, path, status (expected, default 200), name (remember the answer as {name.field}), as (sign in as an account),
on (talk to a peer instead), client (x-client header, for the broker), list (the answer is a list: check the first item),
raw (not JSON), retry (seconds to keep asking: messages arrive a moment later), privacy="off".
Children: <body a="1" b="2"/> or <body json='{"nested":true}'/>; <expect fields="a,b"/>, <expect field="a" equals|contains|absent=.../>.
In texts: {rand} (a fresh number), {name.field} (a field from an earlier answer)."""
import argparse, json, random, re, sys, time
import xml.etree.ElementTree as ET
import httpx


def run_contract(path, key="dev-key", out=print):
    root = ET.parse(path).getroot()
    base = {None: f"http://localhost:{root.get('port')}"}
    base.update({p.get("name"): f"http://localhost:{p.get('port')}" for p in root.findall("peer")})
    accounts = {a.get("name"): (a.get("user"), a.get("password")) for a in root.findall("account")}
    priv = root.find("privacy")
    forbid = set(filter(None, (priv.get("forbid") if priv is not None else "").split(",")))
    captured, tokens, rand = {}, {}, str(random.randint(10**9, 10**10 - 1))

    def fill(text):
        def look(m):
            name, _, field = m.group(1).partition(".")
            return rand if m.group(1) == "rand" else str(captured[name][field])
        return re.sub(r"\{([\w.]+)\}", look, text)

    def headers(step):
        h = {"accept": "application/json"}
        who = step.get("as")
        if who:
            if who not in tokens:
                user, pw = accounts[who]
                tokens[who] = httpx.post(base[None] + "/auth/login", json={"username": user, "password": pw}, headers=h).json()["token"]
            h["authorization"] = "Bearer " + tokens[who]
        elif root.get("kind") == "service":
            h["x-service-key"] = key
        if step.get("client"):
            h["x-client"] = step.get("client")
        return h

    def check(step, r):
        """Everything wrong with this answer (an empty list means the step passed), and the object the expectations looked at."""
        problems, probe = [], None
        want = int(step.get("status", "200"))
        if r.status_code != want:
            return [f"status {r.status_code}, expected {want}" + (f": {r.text[:120]}" if r.status_code >= 400 else "")], None
        if step.get("raw"):
            if step.get("content_type") and step.get("content_type") not in r.headers.get("content-type", ""):
                problems.append(f"content type {r.headers.get('content-type')}, expected {step.get('content_type')}")
            return problems, None
        if want >= 300:
            return problems, None
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
        probe = data
        if step.get("list"):
            probe = data[0] if isinstance(data, list) and data else None
            if probe is None:
                return ["expected a non-empty list"], None
        if not isinstance(probe, dict):
            return (["expected a JSON object"] if probe is not None else []), probe
        for e in step.findall("expect"):
            if e.get("fields"):
                missing = [f for f in e.get("fields").split(",") if f not in probe]
                if missing:
                    problems.append("missing fields: " + ", ".join(missing))
                continue
            f, val = e.get("field"), probe.get(e.get("field"))
            if e.get("equals") is not None and str("" if val is None else val) != fill(e.get("equals")):
                problems.append(f"{f} is {val!r}, expected {fill(e.get('equals'))!r}")
            if e.get("contains") is not None and fill(e.get("contains")) not in str(val):
                problems.append(f"{f} is {val!r}, expected it to contain {fill(e.get('contains'))!r}")
            if e.get("absent") and f in probe:
                problems.append(f"{f} should not be in the answer")
        seen = set(probe) if not isinstance(data, list) else {k for row in data if isinstance(row, dict) for k in row}
        if step.get("privacy") != "off" and forbid & seen:
            problems.append("this organisation must not return: " + ", ".join(sorted(forbid & seen)))
        return problems, probe

    passed = failed = 0
    out(f"Contract: {root.get('service')} (version {root.get('version')}) at {base[None]}")
    for step in root.findall("step"):
        where, problems, probe = step.get("on"), [], None
        label = (step.get("method") + " " + step.get("path") + (f"  [as {step.get('as')}]" if step.get("as") else "")
                 + (f"  [client {step.get('client')}]" if step.get("client") else "") + (f"  [on {where}]" if where else "")
                 + (f"  (expects {step.get('status')})" if step.get("status") else "") + (f"  (waits up to {step.get('retry')}s)" if step.get("retry") else ""))
        try:
            path = fill(step.get("path"))
            body_el = step.find("body")
            body = {k: fill(v) for k, v in (body_el.attrib.items() if body_el is not None else [])}
            if body_el is not None and body_el.get("json"):  # a body that is not flat, written as JSON text
                body = json.loads(fill(body_el.get("json")))
            deadline = time.time() + float(step.get("retry", 0))
            while True:
                r = httpx.request(step.get("method"), base[where] + path, json=body if step.get("method") in ("POST", "PUT") else None,
                                  headers=headers(step), timeout=30)
                problems, probe = check(step, r)
                if not problems or time.time() >= deadline:
                    break
                time.sleep(0.5)  # messages arrive a moment later: ask again
            if not problems and step.get("name") and probe is not None:
                captured[step.get("name")] = probe
        except KeyError as e:
            problems = [f"needs {e} from an earlier step, which did not produce it"]
        except httpx.HTTPError as e:
            problems = [f"no answer from {base[where]} ({type(e).__name__}). Is it running?"]
        if problems:
            failed += 1
            out(f"  [FAIL] {label}\n         " + "\n         ".join(problems))
        else:
            passed += 1
            out(f"  [ ok ] {label}")
    out(f"  -> {passed} passed, {failed} failed")
    return passed, failed


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("contract")
    ap.add_argument("--key", default="dev-key", help="service key (default dev-key, what each module's run.py uses)")
    a = ap.parse_args()
    sys.exit(1 if run_contract(a.contract, a.key)[1] else 0)
