"""Does the portal only use things the gateway offers?  (no servers needed)

    python contracts/check_portal.py gateway/gateway.xml client/portal.xml

For every role: each list, tile and chart must read a route the role may GET; each form and button must call a route the
role may use; every role the gateway can create accounts for (<staff-role>) needs a dashboard and the other way round."""
import re, sys
import xml.etree.ElementTree as ET


def check(gateway_xml, portal_xml):
    gw, pt = ET.parse(gateway_xml).getroot(), ET.parse(portal_xml).getroot()
    routes = [(r.get("method"), r.get("path"), set(r.get("roles").split(","))) for r in gw.findall("route")]
    routes += [(l.get("method"), l.get("path"), set(l.get("roles").split(","))) for l in gw.findall("local")]
    compiled = [(m, re.compile(re.sub(r"\{\w+\}", "[^/]+", p)), roles) for m, p, roles in routes]

    def allowed(role, method, path):
        concrete = re.sub(r"\{\w+\}", "1", path.split("?")[0])
        return any(m == method and rx.fullmatch(concrete) and ("*" in roles or role in roles) for m, rx, roles in compiled)

    problems, forms = [], {f.get("name"): f for f in pt.findall("form")}
    gw_roles, portal_roles = {r.get("role") for r in gw.findall("staff-role")} | {u.get("role") for u in gw.findall("user")}, {r.get("name") for r in pt.findall("role")}
    for r in sorted(gw_roles - portal_roles):
        problems.append(f"the gateway can create '{r}' accounts but portal.xml has no dashboard for that role")
    for r in sorted(portal_roles - gw_roles):
        problems.append(f"portal.xml has a dashboard for role '{r}' but the gateway cannot create accounts with that role (no <staff-role>)")
    for role in pt.findall("role"):
        rn = role.get("name")
        for el in role.iter():
            if el.tag in ("stat", "panel", "chart") and not allowed(rn, "GET", el.get("source")):
                problems.append(f"{rn}: the {el.tag} '{el.get('title') or el.get('label')}' reads {el.get('source')}, which the gateway does not allow for this role")
            if el.tag == "rowaction" and el.get("method") and not allowed(rn, el.get("method"), el.get("path")):
                problems.append(f"{rn}: the button '{el.get('label')}' calls {el.get('method')} {el.get('path')}, which the gateway does not allow for this role")
            if el.tag == "rowaction" and el.get("download") and not allowed(rn, "GET", el.get("download")):
                problems.append(f"{rn}: the button '{el.get('label')}' downloads {el.get('download')}, which the gateway does not allow for this role")
        used = {b.get("form") for b in role.findall("button")} | {x.get("form") for x in role.iter("rowaction") if x.get("form")}
        for name in sorted(used):
            f = forms.get(name)
            if f is None:
                problems.append(f"{rn}: uses form '{name}' which portal.xml does not define")
            elif not allowed(rn, f.get("method"), f.get("path")):
                problems.append(f"{rn}: form '{name}' sends {f.get('method')} {f.get('path')}, which the gateway does not allow for this role")
    return problems


if __name__ == "__main__":
    found = check(sys.argv[1], sys.argv[2])
    print("\n".join(found) or "portal and gateway agree")
    sys.exit(1 if found else 0)
