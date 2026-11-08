"""Client for the message broker (vendored into every service and the gateway; do not edit it in a module).

Broker      send / receive / ack / nack over HTTP + JSON
consume()   a loop that hands each message to a function, acknowledges on success and retries or dead-letters on failure
Permanent   raise it from a handler for a message that can never succeed (bad data): it goes straight to the dead-letter list"""
import asyncio, sys
import httpx


class Permanent(Exception):
    """This message will never be processable. Do not retry it."""


class Broker:
    def __init__(self, url, client, key):
        self.url, self.client, self.key = url.rstrip("/"), client, key
        self._http = httpx.AsyncClient()  # reused for every call

    async def _call(self, path, body, timeout=10, method="POST", params=None):
        headers = {"x-service-key": self.key, "x-client": self.client, "accept": "application/json"}
        r = await self._http.request(method, self.url + path, json=body, params=params, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r

    async def send(self, destination, body, headers=None, correlation_id=None, reply_to=None, priority=4, ttl_seconds=None):
        r = await self._call("/send", {"destination": destination, "body": body, "headers": headers or {}, "correlation_id": correlation_id,
                                       "reply_to": reply_to, "priority": priority, "ttl_seconds": ttl_seconds})
        return r.json()

    async def receive(self, destination, wait=10, selector=""):
        r = await self._call("/receive", {"destination": destination, "wait": wait, "selector": selector}, timeout=wait + 10)
        return None if r.status_code == 204 else r.json()

    async def ack(self, message_id):
        await self._call("/ack", {"id": message_id})

    async def nack(self, message_id, reason="", delay=None, dead=False):
        body = {"id": message_id, "reason": reason, "dead": dead}
        if delay is not None:
            body["delay"] = delay
        await self._call("/nack", body)

    async def admin(self, path, body=None, params=None):
        r = await self._call(path, body, method="POST" if body is not None else "GET", params=params)
        return r.json()


async def consume(broker, destination, handler, selector="", name=""):
    """Receive forever. handler(message) returns normally = acknowledge; raises Permanent = dead-letter; raises anything else = retry."""
    warned = False
    while True:
        try:
            msg = await broker.receive(destination, wait=5, selector=selector)
            warned = False
        except httpx.HTTPError as e:  # broker down or refusing: wait and try again (messages are safe in the broker)
            if not warned:
                print(f"[{broker.client}] cannot receive from {destination}: {type(e).__name__} {e}. Retrying.", file=sys.stderr, flush=True)
                warned = True
            await asyncio.sleep(2)
            continue
        if msg is None:
            continue
        try:
            await handler(msg)
            outcome = ("ack",)
        except Permanent as e:
            outcome = ("nack", str(e)[:200], None, True)
        except Exception as e:  # noqa: BLE001  anything else is treated as temporary
            outcome = ("nack", f"{type(e).__name__}: {e}"[:200], 2, False)
        try:
            await (broker.ack(msg["id"]) if outcome[0] == "ack" else broker.nack(msg["id"], outcome[1], outcome[2], outcome[3]))
        except httpx.HTTPError:
            pass  # the broker will offer the message again after its visibility timeout; the handler must cope with a repeat
