# How the systems are integrated

Four organisations, one gateway, one message broker and one Java system. This page says **which kind of connection is used where, and why**,
what happens when something fails, and how it compares with the design document (Tasks 1 and 2).

## 0. Three languages, one contract

The organisations are written in different languages on purpose, because the point of integration is that systems built by different teams, with
different tools, still work together:

| Module | Language / runtime | Own data | How it joins |
|---|---|---|---|
| hospital_service, specialist_service | Python 3 (FastAPI, shared XML-driven engine) | SQLite | REST + broker |
| **lab_service** | **Java** (JDK classes only: `HttpServer`, `HttpClient`, DOM XML) | `lab.json`, written atomically | REST + broker |
| **pharmacy_service** | **Node.js** (Express, built-in `node:sqlite`) | SQLite | REST + broker |
| analyzer | Java | none | broker only |
| gateway, broker | Python 3 | SQLite | REST (gateway), HTTP + JSON (broker) |
| client | JavaScript, HTML, XSL | none | REST through the gateway |

What makes them interchangeable is the **contract**, not a shared library. Each organisation re-implements the same small agreement on its own:

1. the endpoints and JSON field names in `contracts/<name>.contract.xml` (checked by `contracts/check_contract.py` against the running service);
2. `x-service-key`: only the gateway and sibling services may call it (`401` otherwise);
3. `x-user` / `x-role`: the gateway says who is acting, and the service records it (`requested_by`, `technician`, `doctor`, `pharmacist`);
4. the broker's HTTP + JSON protocol (`/send`, `/receive`, `/ack`, `/nack`), with a **transactional outbox** and, for consumers, an **idempotent** "message already handled" note;
5. JSON errors as `{"detail": ...}` with the same status codes (`404` not found, `409` already exists, `422` bad input).

The gateway, the portal and the Python services cannot tell which language is behind a port. Proof: `python check.py` (every contract) and
`pytest` (118 integration and fault-tolerance tests) pass with the Java lab and the Node.js pharmacy, without changing the gateway, the portal or the
contracts. The Python versions of the same two organisations are kept in `fallback_python/` and satisfy the same contracts (see its README).

What each language version does for the shared behaviour:

| Behaviour | Python engine | Java lab | Node.js pharmacy |
|---|---|---|---|
| Tables and messages declared in `service.xml` | `engine/service.py` | `Config.java` reads it | `src/config.js` reads it |
| Record + outbox saved together | two steps (record, then outbox) | one atomic file write | one SQLite transaction |
| Idempotent consumer | `_processed` table | `processed` ids in the same write as the change | not needed: the pharmacy only sends |
| Business rules | `hooks.py` | none needed (the lab has no rules beyond the XML) | `src/rules.js` (allergy, interaction) |

Honest limits: the Java lab keeps its data in a JSON file rewritten after every change (this build could not download a JDBC driver; swap `Store.java`
for JDBC for real use), and it is plain `HttpServer`, not Spring Boot (Maven Central was not reachable here). The REST contract is identical, so a
Spring Boot version could replace it without touching anything else.

## 1. Two ways of talking, each used where it fits

| Style | Used for | Why |
|---|---|---|
| **REST over HTTP + JSON, through the gateway** | log in, search, read, register, create a consultation, **the prescription** (it must answer at once with the allergy and interaction check), the combined patient history, the discharge PDF | the caller needs the answer now |
| **Messages through the broker** | requests that must not be lost while a service is offline, results coming back from the analyzer, "the pharmacy dispensed, close the case", and announcements ("a lab result is ready") that become notifications | the sender should not have to wait for, or even know about, the receiver |

The rule of thumb in the team: **if the caller needs the answer to carry on, use REST. If it only needs to be sure the other side will get it, send a message.**

## 2. The message patterns in this project

| Pattern | Where | What it gives you |
|---|---|---|
| **Point-to-point queue** | `lab.requests`, `specialist.referrals`, `hospital.case-closed` | exactly one receiver handles each message |
| **Store and forward** | the gateway, for `POST /lab/requests` and `POST /referrals` when the service is offline: the answer is `202 Accepted` and the request waits in the queue | "A request stays pending until the service can process it" (design document 2.8.1) |
| **Guaranteed delivery** | the pharmacy tells the hospital to close the case (FR9) | works even if the hospital is down at that moment |
| **Request / reply with a correlation id** | the lab sends an order to `lab.analyzer.orders`, the Java analyzer answers on `lab.analyzer.results` with the same correlation id (the request number) | two systems, one conversation, no direct connection |
| **Publish / subscribe** | topic `events`, durable subscription `gateway-notifications` | each organisation announces what happened; the gateway turns events into the bell notifications. A new subscriber (an audit trail, a dashboard) can be added in `broker.xml` without touching the publishers |
| **Transactional outbox** | every service: a message to send is first saved in the service's own database (`_outbox`), then forwarded to the broker | if the broker is down, nothing is lost: the pharmacy still dispenses, and the message goes out when the broker is back |
| **Idempotent consumer** | every service: `_processed` remembers which message ids were handled | a message delivered twice is only acted on once |
| **Acknowledgement and redelivery** | broker | a message that was received but not acknowledged within 10 seconds is offered again |
| **Dead-letter queue** | broker | a message that can never succeed (for example a case that does not exist) is set aside with its reason; it does not block the messages behind it. The administrator can retry them in the portal (Administration, Messaging) |
| **Access control per destination** | `broker.xml` | the lab may receive from `lab.requests` but may not send to `hospital.case-closed` |
| **Heterogeneous system** | the Java lab analyzer, the Java lab service, the Node.js pharmacy | a different language and runtime joins the system with only the contract, the broker's address and its name |

## 2b. People and roles

Many people can hold the same role (three doctors, two receptionists...). The administrator creates each account in the portal; the gateway keeps the sign-in, and the person's organisation keeps their working record (a doctor's days and hours, a specialist's specialty).
After checking the token the gateway tells each service **who is acting**, so records say who made them and services can apply ownership rules:

| Rule | Where it is enforced |
|---|---|
| Only receptionists register patients | gateway route |
| Prescriptions are written on the doctor's side only | gateway route |
| A consultation belongs to the doctor who started it; only they treat or close it | hospital rule |
| Appointments are booked against the doctors' working days, hours and time off; if the doctor is not free, the next available doctor, else the next free slot | hospital rule (`schedule`) |
| A referral goes to a specialist of the specialty asked for (the least busy one); only that specialist sees and answers it | specialist rules |
| A specialist **treats** the patient or **recommends** a treatment to the referring doctor; the doctor's consultation shows the outcome | specialist rule and a message to the hospital |
| Notifications go to the doctor concerned, not to every doctor | `<notify user="...">` in `gateway.xml` |

## 3. The flows

```
Doctor treats or refers        doctor (own consultation) -> Treat: diagnosis and plan | Refer: specialist of that specialty, least busy
                               specialist answers: treated, or recommended  --message--> hospital.case-updates --> the consultation's outcome

Doctor orders a test           portal -> gateway --REST--> lab service (saves it as pending)
   lab service is offline  ->  gateway --message--> lab.requests  (202 Accepted; delivered when the lab is back)
   lab service --event--> events topic --> gateway --> notification "New lab test" for the lab technician
   automated test (Blood glucose, Malaria rapid test):
       lab service --order--> lab.analyzer.orders --> JAVA ANALYZER --result--> lab.analyzer.results --> lab service
       lab service --event--> events --> gateway --> notification "Lab result ready" for the doctor

Doctor sends a prescription    portal -> gateway --REST--> hospital (adds the allergy list) --REST--> pharmacy
                               pharmacy answers at once with the allergy warning and the interaction check
                               pharmacy --event--> events --> notifications for the pharmacist (and the doctor if there is a warning)

Pharmacist dispenses (FR9)     pharmacy marks it dispensed, saves two messages in its outbox, and answers the pharmacist
                               outbox --> hospital.case-closed --> hospital closes the consultation
                               outbox --> events --> notification "Dispensed" for the doctor
```

## 4. What happens when something fails (all of these are tests)

| Failure | What happens |
|---|---|
| lab service down, doctor orders a test | `202`, "saved and will be delivered automatically"; the lab gets it when it returns, exactly once |
| pharmacy down, doctor prescribes | `503`: a prescription needs the immediate allergy answer, so it is refused clearly, not queued |
| broker down, pharmacist dispenses | dispensing succeeds; the "close the case" message waits in the pharmacy's outbox; when the broker returns the hospital closes the case and the doctor is notified |
| a service crashes while handling a message | the message is offered again after 10 seconds |
| a bad message (case that does not exist) | dead-lettered with the reason `404`; messages behind it are unaffected |
| the Java analyzer is not running | automated orders wait in `lab.analyzer.orders`; the technician can still enter results by hand |

## 5. "Java messaging" and JMS: what this is, and is not

JMS (Java Message Service) is a **Java programming interface**, normally used with a broker such as ActiveMQ or RabbitMQ's JMS client.
The design document chose Python and REST, and a real JMS broker could not be installed in the build environment, so:

- the broker is written in Python and has JMS-style behaviour: queues, topics with durable subscriptions, acknowledgement, redelivery, dead-letter, priority, expiry (`ttl_seconds`), message selectors, correlation id and reply-to;
- it speaks plain HTTP + JSON, so any language can use it. The Java analyzer uses `analyzer/src/PpsMessaging.java`, a small client shaped like JMS (`Connection`, `Session`, `MessageProducer`, `MessageConsumer`, `Message.acknowledge()`).

| JMS idea | Here |
|---|---|
| `Queue` / `Topic` | `<queue>` / `<topic>` in `broker.xml` |
| durable subscription | `<subscription>` inside a topic |
| `CLIENT_ACKNOWLEDGE` | `POST /ack`; `POST /nack` to refuse |
| `JMSCorrelationID`, `JMSReplyTo` | `correlation_id`, `reply_to` |
| `JMSPriority`, `JMSExpiration` | `priority`, `ttl_seconds` |
| message selector | `selector` (`type=LabResultReady`) |
| redelivery count, dead-letter queue | `deliveries`, the dead-letter list |

If your course needs a real JMS provider, the only code that would change is `integration/engine_src/messaging.py` and `broker/`: the services declare *what* they send and receive in XML, not *how*.

## 6. How this compares with the design document

| Document says | In this build |
|---|---|
| One service per organisation, REST, JSON, an API gateway, JWT with roles, passwords as hashes, audit log | **as designed** |
| Endpoints of section 2.7 | **all present** (including `PUT /consultations/{id}/diagnosis` and `/close`; `GET /lab/requests?status=pending`) |
| 503 when a service is down, the others keep working | **as designed** |
| "A request stays pending until the service can process it" | **delivered with the broker**: lab requests and referrals are kept (202) and delivered when the service returns |
| "All communication uses HTTP requests that carry JSON"; services exchange information only through the gateway and the REST endpoints | **extended**: the broker, the Java analyzer and the outbox go beyond this. The design document needs a short addition (2.3 architecture, 2.4 communication, 2.5 patterns) |
| Data minimisation: the lab gets the patient's ID, **age** and test type | **partly**: the lab gets the patient number and the test, not the age |
| Ids such as `P-1001`, `LR-0001`, `C-2001`, `RX-77` | **different**: numeric ids (1, 2, 3...). Display codes could be added |
| Lab request fields `request_id`, `test_type`, `consultation_id` | **different names**: `id`, `test`, and no consultation id on the lab request |
| Layered Controller / Service / Repository inside each service, Pydantic DTOs | **different**: the Python services use one shared XML-driven engine for all three jobs; the Node.js pharmacy has routes (`server.js`), rules (`src/rules.js`) and a repository (`src/store.js`); the Java lab has `Main` (routes), `Config`, `Store`. The contracts and table definitions play the role of the DTOs |
| One technology stack for all services | **different**: three languages (Python, Java, Node.js), joined only by the contract (section 0) |
| Audit log records user, action, **patient** and time | **partly**: user, role, method, path and time (including every sign-in and failed sign-in); the patient appears in the path where the route has one. Records also say who made them (doctor, receptionist, technician, pharmacist) |
| Users have a role in the token | **as designed**, and many people can share a role |
| HTTPS | not in the demo (the document allows local HTTP) |
| Postman or Insomnia for testing | tests are automated (`pytest`); `/docs` on the gateway lists the endpoints |
