# Message broker (port 8005)

**You own:** the messaging backbone. JMS-style queues and topics with durable subscriptions, acknowledgement, redelivery, dead letters, priority, expiry,
selectors, correlation id and reply-to, and who may use which destination. Database: `broker.db`. Read `docs/INTEGRATION.md` first.

## Your files
| File | What it holds |
|---|---|
| `broker.xml` | every queue and topic, who may send and receive, the retry rules (`visibility_seconds`, `retry_delay_seconds`, `max_deliveries`) |
| `broker.py` | the broker (about 250 lines): `/send`, `/receive` (long poll), `/ack`, `/nack`, `/admin/destinations`, `/admin/messages`, `/admin/retry` |
| `engine/` | the team's shared pieces (`pages.py` for the styled page). Do not edit. |
| `contract.xml` | the agreed behaviour. Do not edit. |

## What the others rely on (the contract)
- `POST /send` `{destination, body, headers, correlation_id, reply_to, priority, ttl_seconds}`: a queue gets one copy, a topic one copy per subscription. `403` if the client may not send there, `404` for an unknown destination.
- `POST /receive` `{destination, wait, selector}`: the best waiting message (highest priority, then oldest), or `204`. The message is invisible to others until acknowledged.
- `POST /ack` `{id}`, `POST /nack` `{id, dead, delay, reason}`. Only the receiver can settle a message. A message is delivered at most `max_deliveries` times, then dead-lettered.
- Admin calls are for the gateway only (`admin="gateway"`).
- Every call needs `x-service-key` and `x-client`. `x-client` decides what the caller may do.

## Good to know
- To add a queue: add a `<queue>` to `broker.xml`, then a `<consume>` or `<send>` in the service that uses it. No code.
- To add a subscriber to the events topic: add a `<subscription>`. Publishers do not change.
- Delivery is **at least once**: a consumer can see a message twice. The service engine already ignores repeats.

## Ideas to build
- A `GET /admin/stream` (server-sent events) so the portal's Messaging tab updates live.
- Message expiry reports, a "purge" for old dead letters, per-destination limits (reject when a queue is too full).
- Delayed delivery (`deliver_after_seconds`) and scheduled messages (for example appointment reminders).
- Swap the storage for a real broker (ActiveMQ, RabbitMQ) behind the same `/send` and `/receive`, so nobody else has to change.

## How you work, and hand over
1. `python run.py` here runs only the broker (`x-service-key: dev-key`). `python run.py` at the top folder runs everything.
2. `python check.py` must end with **READY TO HAND OVER**.
3. Send back **only `broker/`**, zipped.
