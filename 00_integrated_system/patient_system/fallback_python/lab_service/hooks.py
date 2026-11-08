"""Business rules in Python (only where service.xml cannot express them).
Register a function in HOOKS, then use it in service.xml:  <endpoint ... action="insert" hook="my_rule"/>
A hook gets the row about to be saved (a dict), run(sql, args) for this service's own database, and the service.xml root.
It changes the row in place. Example:

def national_id_format(row, run, root):
    if row["national_id"] and not row["national_id"].isdigit():
        raise ValueError("national ID must be digits")
"""
HOOKS = {}
