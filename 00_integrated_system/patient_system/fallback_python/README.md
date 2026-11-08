# Python fallback for the laboratory and the pharmacy

The laboratory (Java) and the pharmacy (Node.js) were first written in Python on the shared engine. Those versions are kept here **unchanged** as a safe fallback
and as a reference for the contract: the same `contract.xml`, the same endpoints, the same messages.

Use them only if the demo machine has no Java or no Node.js:

1. Move `lab_service/` and/or `pharmacy_service/` out of the project's top folder (for example into a folder called `native_versions/`).
2. Copy the Python folder from here to the top folder, in its place.
3. `python run.py`. The start-up list now shows "Python (FastAPI)" for that module.

Nothing else changes: the gateway, the portal and the other organisations cannot tell the difference. This folder is **not** started by `run.py`.
