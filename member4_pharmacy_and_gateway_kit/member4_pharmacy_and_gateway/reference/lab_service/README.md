# Laboratory service (port 8002), written in Java

**You own:** test requests and their results. Data: `lab.json` (see "Why a JSON file" below). The lab only ever knows a **patient number**, never a name.
**Language:** Java, JDK classes only (no Maven, no Gradle, no libraries). Java 11 or newer; a JRE is enough, the launcher compiles the sources itself.

## What the others rely on (the contract)
| Endpoint | Purpose |
|---|---|
| `POST /lab/requests` | a doctor orders a test (`patient_id`, `case_id`, `test`). Answered `pending`. Automated tests (Blood glucose, Malaria rapid test) are also ordered from the Java analyzer |
| `GET /lab/requests` | list, filter with `?patient_id=` or `?status=` |
| `PUT /lab/results/{id}` | the technician (or the analyzer) enters the `result`; `status` becomes `completed` |
| `POST/GET/PUT /lab/staff` | the lab's own technicians |

Messages (declared in `service.xml`, handled by `Main.java`): **receives** `lab.requests` (requests saved by the gateway while the lab was offline) and
`lab.analyzer.results` (results from the analyzer, the correlation id is the request number); **sends** `LabRequested` and `LabResultReady` events and the
orders to `lab.analyzer.orders`.

## The code
| File | Job |
|---|---|
| `src/pps/lab/Main.java` | HTTP server (`com.sun.net.httpserver`), the service-key check, routing, the outbox relay and the queue consumers |
| `src/pps/lab/Config.java` | reads `service.xml` (tables, endpoints, messages) with the JDK's XML parser |
| `src/pps/lab/Store.java` | the lab's own data: records, outbox, "message already handled" notes; every change saved in one atomic write |
| `src/pps/lab/Broker.java` | client for the broker (send, receive, ack, nack) over `java.net.http` |
| `src/pps/lab/Json.java`, `HttpError.java` | a small JSON reader/writer and an error that carries a status code |

## Why a JSON file, and not Spring Boot
The JDK has no database and the build environment could not download a JDBC driver or Spring Boot, so the data is one JSON file rewritten atomically after
every change (temporary file, then rename). That is fine for a demo and keeps the record, its outbox messages and its "handled" note consistent. For real
use, replace `Store.java` with a JDBC version; the rest does not change. A Spring Boot version could replace the whole module because it only has to keep `contract.xml`.

## How you work
1. `python run.py` in this folder compiles (first time) and runs **only the lab** (port 8002). Calls need the header `x-service-key: dev-key`.
2. See it in the whole system: from the top folder run `python run.py`, then open http://localhost:8000/ui/
3. Before you hand over: `python check.py` from the top folder. It must end with **READY TO HAND OVER**.

## Rules
- **Do not edit `contract.xml`.** It is the agreement with the other members. Add fields and endpoints freely, but the ones in the contract must keep working exactly as written.
- Keep to your own data. Never read another organisation's data, and never store its data here (the contract's `privacy` line checks this).
- `lab.json` is created in the data folder the first time you run; it is ignored by git. Delete it to start fresh.
