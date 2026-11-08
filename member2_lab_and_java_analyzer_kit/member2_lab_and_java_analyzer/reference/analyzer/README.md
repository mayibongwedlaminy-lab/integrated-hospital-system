# Lab analyzer (Java)

**You own:** an independent Java program that plays the laboratory's automated analyzer. It is a *different system in a different language*,
and it joins the project only through the message broker.

```
lab service --order--> lab.analyzer.orders --> LabAnalyzer.java --result (same correlation id)--> lab.analyzer.results --> lab service
```

## Your files
| File | What it holds |
|---|---|
| `src/PpsMessaging.java` | a small JMS-style client: `Connection`, `Session`, `MessageProducer`, `MessageConsumer`, `Message.acknowledge()` / `reject()`. No libraries (Java 11 or newer). |
| `src/LabAnalyzer.java` | the analyzer: receives an order, "measures", sends the result back, then acknowledges |
| `run.py` | compiles and runs it (uses `javac`, or the compiler inside the JVM) |
| `contract.xml` | the agreed behaviour. Do not edit. |

## What the others rely on
- It receives orders on **`lab.analyzer.orders`**: `{"id": <request number>, "patient_id": ..., "test": "Blood glucose"}` with `correlation_id` = the request number and `reply_to` = `lab.analyzer.results`.
- It answers on `reply_to` with `{"request_id": ..., "result": "6.2 mmol/L"}` and the **same correlation id**. The lab service completes the request from that.
- It acknowledges an order only **after** the reply was sent, so a crash in between means the order is offered again.
- A test it has no method for is **rejected to the dead-letter list**, with a reason the administrator can read in the portal.
- Its broker name is `analyzer`: it may receive orders and send results, nothing else (`broker.xml`).

## Good to know
- Which tests are automated is decided by the lab's `service.xml` (`<send ... to="lab.analyzer.orders" when="test=...">`), and by `analyse()` here. Keep both in step.
- It has no REST interface and never touches the lab's database.
- If Java is not installed, the system runs without it and the technician enters results by hand.

## Ideas to build
- More tests and realistic ranges; flag abnormal values; send a `critical` header the portal can show.
- Run several analyzers at once (they share the queue: each order goes to one of them).
- A second Java program: a **pharmacy stock agent** that listens to the events topic and keeps a stock level (add a subscription in `broker.xml`).
- Rewrite `PpsMessaging` on top of a real JMS provider and keep `LabAnalyzer` unchanged.

## How you work, and hand over
1. `python run.py` at the top folder starts everything including your analyzer; order "Blood glucose" as the doctor and watch the result arrive.
2. `python check.py` must end with **READY TO HAND OVER** (it needs Java).
3. Send back **only `analyzer/`**, zipped.
