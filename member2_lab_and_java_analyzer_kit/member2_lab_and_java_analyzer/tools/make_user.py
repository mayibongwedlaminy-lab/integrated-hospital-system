"""Make the STARTING account line for gateway/gateway.xml:  python tools/make_user.py
Only a salted PBKDF2 hash is printed, never the password.
Accounts in gateway.xml are created once, on the very first start. After that, add people in the portal (Administration, Add staff member)."""
import getpass, hashlib, secrets

name = input("Username: ").strip()
role = input("Role (receptionist, doctor, lab_technician, specialist, pharmacist, administrator): ").strip()
pw = getpass.getpass("Password (at least 10 characters): ")
if len(pw) < 10:
    raise SystemExit("Too short.")
salt = secrets.token_hex(8)
print(f'\n  <user name="{name}" role="{role}" salt="{salt}"\n        hash="{hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 100_000).hex()}"/>\n')
print("Replace the <user> line in gateway/gateway.xml BEFORE the first start. (An existing database keeps its accounts: add people in the portal instead.)")
