"""Pharmacy business rules (FR8). service.xml uses them as  hook="allergy,interaction".
Each gets the prescription about to be saved, run(sql, args) for the pharmacy database, and the service.xml root."""


def allergy(row, run, root):  # FR8: business rule that XML cannot express
    hits = [a.strip() for a in row["allergies"].split(",")
            if a.strip() and a.strip().lower() in row["drug"].lower()]
    row["warning"] = "ALLERGY CONFLICT: " + ", ".join(hits) if hits else ""


def interaction(row, run, root):  # new drug against everything else already prescribed to this patient
    prior = [r["drug"] for r in run("SELECT drug FROM prescriptions WHERE patient_id=?", (row["patient_id"],))[0]]
    found = []
    for p in root.findall("interactions/pair"):
        a, b = p.get("a").lower(), p.get("b").lower()
        for other in prior:
            new, old = row["drug"].lower(), other.lower()
            if (a in new and b in old) or (b in new and a in old):
                found.append(f"{p.get('level').upper()}: {row['drug']} with {other}, {p.get('note')}")
    row["interaction"] = "; ".join(dict.fromkeys(found))


HOOKS = {"allergy": allergy, "interaction": interaction}
