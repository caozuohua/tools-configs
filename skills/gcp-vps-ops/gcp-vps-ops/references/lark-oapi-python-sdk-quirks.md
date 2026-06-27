---
title: lark_oapi Python SDK v1.6.8 — WebSocket client quirks on a VPS
source: real session 2026-06-18, instance-20260413-080555 (e2-micro 1 GB)
applies_to: building a Lark/Feishu WebSocket bot in Python (not the HTTP webhook pattern), deploying it to a constrained VPS alongside other services
---

# lark_oapi Python SDK v1.6.8 — WebSocket client quirks

`lark_oapi` is the official Python SDK for Lark/Feishu (Larksuite
international + feishu.cn). v1.6.8 is what nanobot uses and what we
adopted for the Hermes Lite `lark_adapter.py` prototype. This reference
captures the **verified** API surface and gotchas that aren't obvious
from the docs.

## Mode 1 — HTTP (one-shot calls)

Use `lark.Client` for one-shot API calls (read/write records, send a
message in response to a webhook, etc.). Covered extensively in
`references/lark-api-write-via-remote-vps.md`. Doesn't need long-lived
state — fine for cron-style jobs.

## Mode 2 — WebSocket (event subscription, the bot pattern)

Use `lark.ws.Client` (or `lark.Client` + `EventDispatcherHandler`) for
event-driven bots that need to receive messages in real time.
WebSocket is **the right choice** when:

- You don't want to expose a public HTTP webhook (firewall pain,
  certificate hassle, GCP firewall rules)
- You're on a VPS behind NAT with no public inbound port
- Mobile client is Lark (WSS works from China without VPN)

## Mode 3 — WebSocket + your own client (the rare case)

The `lark_oapi` SDK has BOTH an HTTP `Client` AND a separate `ws.Client`
that does WebSocket internally. For a bot that just needs to receive
events and reply, `lark.ws.Client` is simpler — no manual dispatcher.

```python
import lark_oapi as lark
from lark_oapi.ws import Client as WSClient

client = (
    WSClient.builder()
    .app_id(app_id)
    .app_secret(app_secret)
    .domain(lark.LARK_DOMAIN)  # REQUIRED for international; see below
    .event_handler(handler)    # sync function(msg) -> None
    .build()
)
client.start()  # blocks forever
```

For more control (custom dispatch, multiple event types), use
`lark.Client.builder()...build()` + `EventDispatcherHandler.builder(...)`.

## Domain — the LARK_DOMAIN constant (critical)

**Default SDK domain is `https://open.feishu.cn`** (Feishu China).
If your app is registered on **Larksuite international** (larksuite.com,
e.g. `cli_a97ca8e4d3389e18` on `https://open.larksuite.com`), you MUST
explicitly set the domain. Otherwise every API call fails with:

```json
{"code": 99991663, "msg": "Incorrect domain name", ...}
```

The exact pattern (verified 2026-06-18):

```python
import lark_oapi as lark

# `lark.LARK_DOMAIN` is a module-level string constant
# (NOT an Enum or object — it's just a string)
# Value: "https://open.larksuite.com"

client = (
    lark.Client.builder()
    .app_id(app_id)
    .app_secret(app_secret)
    .domain(lark.LARK_DOMAIN)   # <-- THE FIX
    .build()
)
```

### How to discover the right constant

```bash
python3 -c "import lark_oapi as l; print([x for x in dir(l) if 'DOMAIN' in x.upper()])"
# Output: ['LARK_DOMAIN']
# (And there's no FEISHU_DOMAIN — the China default is the SDK's hardcoded base.)
```

### Other domain-related gotchas

- `lark.Domain` does NOT exist (you might try `.domain(lark.Domain.LARK)` —
  AttributeError, not a useful error)
- The token-fetch endpoint is the same URL pattern in both domains
  (`/open-apis/auth/v3/tenant_access_token/internal`) — domain switch
  handles it automatically

## CreateMessageRequest — the builder split trap

**The single most common bug** when writing a reply bot in
lark_oapi v1.6.8:

```python
# ❌ WRONG — `CreateMessageRequestBuilder` has NO `receive_id` method
req = (
    CreateMessageRequest.builder()
    .receive_id(chat_id)         # ← AttributeError at runtime
    .msg_type("text")
    .content(json.dumps({"text": reply}))
    .build()
)
```

The correct API (verified by reading
`venv/lib/python3.13/site-packages/lark_oapi/api/im/v1/model/create_message_request.py`
on 2026-06-18):

```python
# ✅ CORRECT — chat_id goes on BODY builder; type goes on REQUEST builder
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
)

body = (
    CreateMessageRequestBody.builder()
    .receive_id(chat_id)         # <-- here
    .msg_type("text")
    .content(json.dumps({"text": reply}))
    .build()
)
req = (
    CreateMessageRequest.builder()
    .receive_id_type("chat_id")  # <-- NOT receive_id, and only the type
    .request_body(body)
    .build()
)
resp = api_client.im.v1.message.create(req)
```

### What the request and body builders each accept

| Builder | Methods | Notes |
|---------|---------|-------|
| `CreateMessageRequestBodyBuilder` | `receive_id(str)`, `msg_type(str)`, `content(str)`, `uuid(str)` | `content` is a JSON-encoded STRING, not a dict |
| `CreateMessageRequestBuilder` | `receive_id_type(str)`, `request_body(body)` | `receive_id_type` is one of `"chat_id"`, `"open_id"`, `"email"`, `"union_id"` |

`receive_id_type` defaults to `"open_id"` if omitted — most messages
should explicitly set `"chat_id"`.

## Memory profile (lark_oapi v1.6.8 on e2-micro 1 GB VPS)

Measured 2026-06-18 with one idle `lark_adapter.py` process (WS
connected, no messages handled yet):

| Metric | Value |
|---|---|
| RSS | 175 MB |
| VSZ | ~750 MB |
| Python interpreter + lark_oapi + websockets + stdlib | the bulk |

**On a 1 GB VPS, you can run ONE lark_oapi process comfortably.** Adding
a second one (~350 MB total) leaves < 100 MB free, triggers swap, and
risks OOMKill. If you need redundancy or multiple bots, deploy to a
larger instance (e2-small = 2 GB is comfortable).

The Python interpreter alone is ~30-50 MB; lark_oapi + its dependencies
(websockets, aiohttp, requests, cryptography, etc.) account for the
rest. There is no lean alternative — the SDK pulls in `aiohttp` for the
HTTP fallback path even if you only use WS.

## WebSocket connect — what "success" looks like

After `client.start()`, expect this log line within 5-10 seconds:

```
[Lark] [<timestamp>] [INFO] connected to wss://msg-frontier-sg.larksuite.com/ws/v2
?fpid=493&aid=<APP_ID_INT>&device_id=<RANDOM>&access_key=<HASH>&service_id=33554678
&ticket=<UUID> [conn_id=<DEVICE_ID>]
```

- The URL host is `msg-frontier-sg.larksuite.com` for international
  (Singapore-region fallback). China uses `msg-frontier.feishu.cn`.
- `aid` is the **numeric** form of your `app_id` (e.g. `cli_a97ca8e4d3389e18` → `aid=552564`)
- `device_id` is generated client-side; persists for the SDK's session
- The SDK auto-reconnects on disconnect (heartbeat every ~30s)

If you see `connected to wss://msg-frontier.feishu.cn/...` instead,
your domain is wrong (you're on the China default).

## Inbound message shape — what the handler receives

```python
def on_message(data: P2ImMessageReceiveV1) -> None:
    event = data.event
    sender = event.sender
    msg = event.message
    chat_id = msg.chat_id          # for replies
    chat_type = msg.chat_type      # "p2p" (DM) or "group"
    msg_id = msg.message_id        # for dedup
    text = json.loads(msg.content)["text"]  # content is a JSON string!
```

Trap: `msg.content` is a JSON-encoded STRING (e.g. `'{"text":"hi"}'`),
not a dict. Always `json.loads()` before reading fields.

### The dual-Sender-schema trap — REST API vs WS events

lark_oapi v1.6.8 has TWO different `Sender` classes for the same
logical concept (who sent this message), and they have **different
attribute names**. Mixing them gives `AttributeError` at runtime:

| Transport | Class | Attributes | File |
|---|---|---|---|
| REST API response (`Message`, `ListMessageRequest`, etc.) | `Sender` | `id`, `id_type` ("open_id"\|"user_id"\|"union_id"\|"email"), `sender_type`, `tenant_key`, `sender_name` | `api/im/v1/model/sender.py` |
| WS event payload (`P2ImMessageReceiveV1.event.sender`) | `EventSender` | `sender_id` (UserId object with `open_id`/`user_id`/`union_id`), `sender_type`, `tenant_key` | `api/im/v1/model/event_sender.py` |
| `UserId` (sub-object of EventSender) | `UserId` | `open_id`, `user_id`, `union_id` | `api/im/v1/model/user_id.py` |

**Symptom of mixing**:
```python
m = client.im.v1.message.get(...).data.items[0]   # REST response
print(m.sender.id)         # ← works (REST Sender has .id)
# vs
event = on_msg_data.event  # WS event
print(event.sender.id)     # ← AttributeError — EventSender has no .id
```

Or vice versa:
```python
event = on_msg_data.event
print(event.sender.sender_id.open_id)  # ← works (EventSender.user_id.UserId)
m = client.im.v1.message.get(...).data.items[0]
print(m.sender.sender_id)  # ← AttributeError — REST Sender has no .sender_id
```

**Why this exists**: the v1.6.8 SDK was migrated to the new schema
(`id`/`id_type`) for REST responses but the WS event schema wasn't
fully migrated — events still use the older nested `sender_id` form.
This is undocumented and confusing if you mix transports in one bot.

**For a bot that uses both** (receive via WS, send or query via REST):
- When reading inbound: use `event.sender.sender_id.open_id` (WS schema)
- When reading outbound (REST query): use `m.sender.id` + `m.sender.id_type`
- Don't try to use the same code path for both — write a small adapter
  function that normalizes both shapes into one dict

**For Hermes's bundled `feishu.py`** specifically: it uses the WS schema
(`event.sender.sender_id.open_id`) for inbound and the REST schema for
outbound. The code branches correctly but the field names are
inconsistent across the two paths — see the `g2g...` symptom section in
`hermes-feishu-gateway-deployment.md` for the auth-related consequences.

## Reply gotchas

1. **Rate limits**: 5 messages/sec/chat, 100/sec/app. Burst protection
   the SDK doesn't do for you — add your own queue.
2. **No `at` mention support in v1.6.8 plain text**: to @-mention someone,
   use the `msg_type="post"` (rich text) builder instead of `"text"`.
3. **Card / interactive message types** (`"interactive"`) require a
   different body shape — JSON with `header`, `elements`, etc. See
   the Lark API docs, not covered here.

## Tenant_access_token — don't persist

`tenant_access_token` is short-lived (~2 hours). The lark_oapi SDK
auto-refreshes it when using `lark.Client` — don't fetch manually and
cache it. The SDK's token manager handles refresh transparently.

If you DO need to call APIs outside the SDK (e.g. directly with
`requests`), fetch fresh on each call or on first 99991663 error (NOT
on a fixed schedule — that wastes token-budget).

## Pitfalls

- **Don't pass `domain=` and `app_id=` in the wrong order** — the
  builder is order-independent but readers get confused. Put
  `.domain(lark.LARK_DOMAIN)` BEFORE `.app_id()` for readability:
  "tell the SDK which Lark we're talking to, then who we are."
- **Don't use `lark.ws.Client` if you need to call HTTP APIs from the
  same handler** — `ws.Client` only handles events; for sending
  messages, build a separate `lark.Client` and use its
  `.im.v1.message.create(...)` method.
- **Don't try to instantiate `lark.Domain.LARK`** — there's no Enum;
  the constant is the bare string `lark.LARK_DOMAIN`.
- **Don't trust the SDK's reconnect logs without checking `ps`** — the
  SDK logs "reconnecting..." even on healthy sessions (heartbeat
  packets). `ps -p <PID>` showing running + RSS stable = healthy.
- **`/tmp` for log files is fine on VPS but `lark.log` gets eaten on
  reboot** — write to `/home/<user>/.hermes-lite/` or a systemd-managed
  `/var/log/<app>/` if you need persistence across reboots.
- **Long-running WS bots accumulate `gevent`/`aiohttp` resources** —
  RSS grows ~5-10 MB/day on a quiet WS connection. Monitor with
  `systemctl show <svc> -p MemoryCurrent` daily; >50 MB/day growth
  indicates a leak or unbounded queue.

## Minimal working WS adapter (verified 2026-06-18)

```python
#!/usr/bin/env python3
import json, os, signal, sys, logging
import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    P2ImMessageReceiveV1,
    CreateMessageRequest,
    CreateMessageRequestBody,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
log = logging.getLogger("lark_adapter")

CREDS = os.environ["LARK_CREDS_PATH"]
app_id, app_secret = json.load(open(CREDS)).values()

def on_message(data: P2ImMessageReceiveV1) -> None:
    try:
        msg = data.event.message
        text = json.loads(msg.content).get("text", "").strip()
        chat_id = msg.chat_id
        log.info("recv | chat=%s type=%s text=%r", chat_id, msg.chat_type, text[:200])

        if text in ("ping", "/ping"):
            reply = "pong"
        else:
            reply = f"echo: {text}"

        # ✅ CORRECT builder split
        body = (CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("text")
                .content(json.dumps({"text": reply}))
                .build())
        req = (CreateMessageRequest.builder()
               .receive_id_type("chat_id")
               .request_body(body)
               .build())

        # Need an HTTP client too, because ws.Client doesn't expose im.v1
        api_client = (lark.Client.builder()
                      .app_id(app_id).app_secret(app_secret)
                      .domain(lark.LARK_DOMAIN).build())
        resp = api_client.im.v1.message.create(req)
        if resp.success():
            log.info("reply sent | msg_id=%s", resp.data.message_id)
        else:
            log.error("reply failed | code=%s msg=%s", resp.code, resp.msg)
    except Exception:
        log.exception("on_message error")

def main():
    log.info("starting Lark WS client (Ctrl+C to stop)")
    client = (lark.ws.Client.builder()
              .app_id(app_id).app_secret(app_secret)
              .domain(lark.LARK_DOMAIN)        # <-- required
              .event_handler(on_message)
              .build())
    signal.signal(signal.SIGTERM, lambda *_: client.stop())
    client.start()

if __name__ == "__main__":
    main()
```

## Verified against

- `lark_oapi==1.6.8` (PyPI)
- Python 3.13.3 on Ubuntu 24.04 LTS (e2-micro 1 GB)
- Lark app on Larksuite international (app_id `cli_a97ca8e4d3389e18`)
- WebSocket connect to `msg-frontier-sg.larksuite.com/ws/v2`
- Inbound: p2p DM with `text` content, replied with `text` content
