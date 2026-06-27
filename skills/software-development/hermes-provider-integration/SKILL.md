---
name: hermes-provider-integration
description: Add a new LLM provider/model API to Hermes Agent. Use when wiring a model API (Gemini via Vertex AI, Bedrock, AI Studio, custom aggregator, in-house model) into Hermes so it shows in `hermes model` picker and `/model <provider>:<model>` switching. Covers the 3-layer registry, OpenAI-shape HTTP proxy pattern for non-OpenAI APIs, credential resolution, picker surfacing, E2E test recipe. NOT for plug-and-play providers already in models.dev catalog.
version: 1.0.0
platforms: [linux, macos]
metadata:
  hermes:
    tags: [hermes, llm, provider, model-api, integration, vertex-ai, bedrock, proxy]
    trigger: "When the user wants to add a new model API to Hermes that isn't already in models.dev — new provider slug, custom model endpoint, or non-OpenAI API (Vertex AI / Anthropic Bedrock / Cohere / custom) accessed via /model picker"
---

# Hermes Provider Integration

## Overview

Hermes treats providers as first-class identifiers (`gemini`, `anthropic`, `openrouter`, `bedrock`, `vertexai`, ...) that route through a transport layer (`openai_chat`, `anthropic_messages`, `codex_responses`, `bedrock_converse`). The picker, `/model` command, credential resolution, and the OpenAI-shape client all key off the **provider slug** plus the **transport** in `HERMES_OVERLAYS`.

Two paths exist for adding a new provider:

- **A) The new API speaks OpenAI Chat Completions** (most do — Vertex AI, Bedrock via Converse, AI Studio, OpenRouter, Together, etc. all have OpenAI-compat endpoints). Wire it through the existing `openai_chat` transport. No core change beyond registration.
- **B) The new API is genuinely different** (Anthropic native messages, AWS Bedrock Converse, AWS SDK). Add a new transport and special-case it in `create_openai_client`.

For a new provider that **uses the google-genai library against Vertex AI** (the case that motivated this skill), path A via a **local OpenAI-shape HTTP proxy** is the cleanest — see "The HTTP proxy pattern" below.

## The 3-layer registration

Adding a provider slug like `vertexai` to Hermes requires touching exactly three files in `hermes_cli/`:

### Layer 1 — `hermes_cli/providers.py`

**a)** Add to `HERMES_OVERLAYS` dict (around line 46):

```python
"yourprovider": HermesOverlay(
    transport="openai_chat",       # or anthropic_messages / codex_responses / bedrock_converse
    auth_type="api_key",           # or oauth_device_code / oauth_external / external_process / aws_sdk
    extra_env_vars=("YOUR_API_KEY", "YOUR_BASE_URL"),  # see "credential signal" below
    base_url_override="https://api.yourprovider.com/v1",
    base_url_env_var="YOUR_BASE_URL",
),
```

**b)** Add to `ALIASES` dict (around line 240) for friendly names:

```python
"yourshort": "yourprovider",
"yp": "yourprovider",
```

### Layer 2 — `hermes_cli/models.py`

**a)** Add to `_PROVIDER_MODELS` dict (around line 230) — the curated list of models shown in the picker:

```python
"yourprovider": [
    "your-model-flash",
    "your-model-pro",
],
```

**b)** Add to `CANONICAL_PROVIDERS` (around line 1010) — appears in `hermes model` and the TUI picker:

```python
ProviderEntry("yourprovider", "Your Provider", "Your Provider (one-line description)"),
```

Note: `ProviderEntry` uses `slug` (not `id`) as the constructor name. Test with `any(p.slug == 'yourprovider' for p in CANONICAL_PROVIDERS)`.

### Layer 3 — `hermes_cli/auth.py`

Add to `PROVIDER_REGISTRY` dict (around line 167) so `model_switch.switch_model()` can resolve credentials:

```python
"yourprovider": ProviderConfig(
    id="yourprovider",
    name="Your Provider",
    auth_type="api_key",
    inference_base_url="https://api.yourprovider.com/v1",
    api_key_env_vars=("YOUR_API_KEY",),
    base_url_env_var="YOUR_BASE_URL",
),
```

### The credential signal trick (`extra_env_vars`)

The `/model` picker filters by `has_credentials`. The check at `model_switch.py:1470` is:

```python
elif overlay.extra_env_vars:
    has_creds = any(os.environ.get(ev) for ev in overlay.extra_env_vars)
```

If your provider doesn't have a real API key (e.g., it uses gcloud ADC server-side, or a local proxy that ignores the key), set `extra_env_vars` to **dummy env vars that the user will have set anyway** as a presence signal. Example for a local proxy:

```python
extra_env_vars=("GOOGLE_CLOUD_PROJECT", "YOUR_PROXY_URL"),
```

Add the corresponding env var to `~/.hermes/.env` so the picker surfaces the provider.

## The HTTP proxy pattern (for non-OpenAI-shape APIs)

When the new API uses a non-HTTP-auth or non-OpenAI-shape surface (google-genai library, custom gRPC, in-house model API), **don't write a 600-line in-process OpenAI-shape adapter**. Instead:

1. **Write a small HTTP server** that translates OpenAI-shape requests to the native API. ~200-400 lines, depends only on the standard library + your API client.
2. **Configure the provider as `openai_chat` transport** pointing at `http://127.0.0.1:<port>/v1` in `HERMES_OVERLAYS`.
3. **Run the proxy as a systemd user unit** with `WantedBy=default.target` + enable `loginctl enable-linger <user>` so it auto-starts on boot.

This pattern was verified on 2026-06-21 with `~/.hermes/scripts/vertexai_proxy.py` (google-genai → OpenAI-shape for Vertex AI / Gemini). Working in 380 lines, zero changes to Hermes' transport layer.

### Skeleton of an OpenAI-shape HTTP proxy

```python
#!/usr/bin/env python3
"""<Your provider> proxy — OpenAI-shape HTTP frontend over <your lib>."""
from __future__ import annotations
import json
import os
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DEFAULT_MODEL = "your-default-model"
HOST = os.environ.get("YOUR_PROXY_HOST", "127.0.0.1")
PORT = int(os.environ.get("YOUR_PROXY_PORT", "18999"))


def _to_native_messages(messages: list[dict]) -> tuple[Any, str | None]:
    """Translate OpenAI messages[] → your API's native shape. Return (contents, system_prompt)."""
    # your translation here
    pass


def _from_native_response(resp: Any, model: str) -> dict:
    """Translate your API's response → OpenAI chat.completion shape."""
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": getattr(resp, "text", "") or ""},
            "finish_reason": "stop",
        }],
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def do_GET(self):
        if self.path == "/healthz":
            self._json(200, {"status": "ok", "models": [DEFAULT_MODEL]})
        else:
            self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self._json(404, {"error": {"message": "not found"}})
            return
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8"))
        except Exception as e:
            self._json(400, {"error": {"message": f"bad json: {e}"}})
            return

        # Build native request
        contents, system = _to_native_messages(req.get("messages") or [])
        # Call your API
        client = _make_client()
        resp = client.your_native_call(model=req.get("model", DEFAULT_MODEL), contents=contents, system=system)
        # Return OpenAI shape
        self._json(200, _from_native_response(resp, req.get("model", DEFAULT_MODEL)))

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)


def main():
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"proxy on http://{HOST}:{PORT}/", file=sys.stderr)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
```

### systemd user unit for the proxy

`~/.config/systemd/user/your_proxy.service`:

```ini
[Unit]
Description=Your provider proxy
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/<user>/.hermes/hermes-agent
ExecStart=/home/<user>/.hermes/hermes-agent/venv/bin/python3 /home/<user>/.hermes/scripts/your_proxy.py
EnvironmentFile=/home/<user>/.hermes/.env
Restart=on-failure
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

Then:

```bash
XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user daemon-reload
XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user enable --now your_proxy.service
sudo loginctl enable-linger <user>  # survive logout / reboot
```

## E2E test recipe

After registering a provider, verify in 3 layers:

### 1. Standalone proxy / direct API call

```bash
curl -s http://127.0.0.1:<port>/healthz
curl -s http://127.0.0.1:<port>/v1/models
curl -s -X POST http://127.0.0.1:<port>/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"<model>","messages":[{"role":"user","content":"Reply OK."}],"max_tokens":32}'
```

### 2. OpenAI SDK round-trip (simulates what Hermes does)

```python
import os
for k in ['HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy']:
    os.environ.pop(k, None)

from openai import OpenAI
client = OpenAI(api_key='<any-string>', base_url='http://127.0.0.1:<port>/v1')
resp = client.chat.completions.create(
    model='<model>',
    messages=[{'role':'user','content':'Reply OK.'}],
    max_tokens=32,
)
print(resp.choices[0].message.content, resp.choices[0].finish_reason)
```

### 3. Hermes switch pipeline

```python
import os
for k in ['HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy']:
    os.environ.pop(k, None)

from hermes_cli.model_switch import switch_model, get_authenticated_provider_slugs

# Picker surfaces it
assert 'yourprovider' in get_authenticated_provider_slugs(current_provider='custom')

# Switch resolves
r = switch_model(
    raw_input='<model>',
    current_provider='custom',
    current_model='whatever',
    explicit_provider='yourprovider',
    is_global=False,
)
assert r.success, f"switch failed: {r.error_message}"
assert r.api_mode == 'chat_completions'
assert r.base_url.startswith('http://127.0.0.1:<port>')
```

If all three pass, the provider is wired. Users can now `/model yourprovider:<model>` in any chat.

## Why the HTTP proxy (vs in-process adapter)

For a new transport-shaped library (genai, anthropic native, custom gRPC), the in-process OpenAI-shape adapter path requires:

- Writing a full OpenAI-shape facade in `agent/<lib>_adapter.py` (500-1000 lines, see `agent/gemini_native_adapter.py` for the reference shape).
- Special-casing it in `agent/agent_runtime_helpers.create_openai_client`.
- Adding to `agent/transports/types.py` if it's a new transport type.
- Re-applying the patch every time you rebase upstream.

The HTTP proxy approach:

- ~200-400 lines in `~/.hermes/scripts/your_proxy.py`, zero core changes.
- Survives upstream rebases cleanly (your patches live outside the core tree).
- Independently testable with curl before wiring into Hermes.
- Can be run as a service that other tools (curl scripts, your own tests, side-channel agents) can also use.

The cost is one extra HTTP hop and the proxy needs to be running. For local loopback that's negligible (<1ms). For correctness and maintenance, the trade is clearly favorable.

## Reference: the vertexai integration (2026-06-21)

The first provider added through this skill was `vertexai` (Google Cloud Vertex AI / Gemini via google-genai library):

- **Proxy**: `~/.hermes/scripts/vertexai_proxy.py` (380 lines, supports chat/stream/tool calling/system prompt)
- **systemd unit**: `~/.config/systemd/user/vertexai_proxy.service` (auto-restart, lingering enabled)
- **3 file changes** (each ~15 lines):
  - `hermes_cli/providers.py`: `HERMES_OVERLAYS["vertexai"]` + `ALIASES["vertex","vertex-ai"]`
  - `hermes_cli/models.py`: `_PROVIDER_MODELS["vertexai"]` + `CANONICAL_PROVIDERS` entry
  - `hermes_cli/auth.py`: `PROVIDER_REGISTRY["vertexai"]` (auth_type=api_key, dummy key env var)
- **4 env vars** in `~/.hermes/.env`:
  - `GOOGLE_CLOUD_PROJECT` (also serves as credential signal)
  - `GOOGLE_CLOUD_LOCATION`
  - `VERTEXAI_PROXY_URL=http://127.0.0.1:18999/v1`
  - `VERTEXAI_PROXY_KEY=<any-string>` (proxy ignores, gcloud ADC happens server-side)
- **Verified**: non-stream chat, SSE streaming, tool calling, system prompt, picker surfacing, switch_model pipeline, all through `openai_chat` transport unchanged.

## Common pitfalls

### Provider not appearing in `hermes model` picker

Two causes, in order of likelihood:

1. **`extra_env_vars` doesn't match any set env var.** Check `get_authenticated_provider_slugs()` directly:
   ```python
   from hermes_cli.model_switch import get_authenticated_provider_slugs
   print(get_authenticated_provider_slugs(current_provider='custom'))
   ```
2. **Provider not in `_KNOWN_PROVIDER_NAMES` / `CANONICAL_PROVIDERS`.** Verify with:
   ```python
   import hermes_cli.models as M
   print('yourprovider' in M.CANONICAL_PROVIDERS)  # ProviderEntry needs to be added
   print(any(p.slug == 'yourprovider' for p in M.CANONICAL_PROVIDERS))
   ```

### `switch_model` returns "Unknown provider"

`PROVIDER_REGISTRY` (in `hermes_cli/auth.py`) is missing an entry. The 3 layers are all required — providers.py alone is not enough.

### OpenAI client gets redirected through a corporate proxy

Strip proxy env vars before constructing the client:
```python
import os
for k in ['HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy']:
    os.environ.pop(k, None)
os.environ['NO_PROXY'] = '127.0.0.1,localhost'
```

### `_validate_base_url` rejects the proxy URL

`http://127.0.0.1:<port>/v1` is fine (loopback). Only malformed URLs (bad scheme, bad port) are rejected. If you see a "Malformed custom endpoint URL" error, double-check the URL has a valid scheme + port.

## Gateway & picker post-deploy gotchas

`hermes-gateway` is a long-lived systemd service (started 2026-06-21 on
`gcp-vps2`, e.g. PID 3874) that imports `hermes_cli/*` at startup. **Editing
provider files in `hermes_cli/` and not restarting the gateway means the
running process keeps the OLD module state in memory** — your `cli/main.py`
test (which spawns a fresh `python -c "..."` process) will see the new code,
but the gateway's `/model` picker will still show the old provider list.

Symptoms:
- `hermes_cli.model_switch.list_picker_providers()` from a fresh Python
  process shows the new provider — but `/model` in Discord still doesn't
- `hermes_cli.model_switch.list_authenticated_providers()` returns 5 rows
  (including the new one) — but the Discord picker still shows 4
- The user's report "vertexai 还没出现在 picker 里" — but the code is fine

### Two picker functions, not one

`hermes_cli/model_switch.py` has TWO functions that return picker rows.
Both must surface the new provider or one path will silently drop it:

| Function | Line | Caller | Output type |
|---|---|---|---|
| `list_authenticated_providers()` | ~1202 | Text fallback in `gateway/slash_commands.py:1168` (when platform has no picker) | flat list of dicts |
| `list_picker_providers()` | ~2029 | Interactive picker in `gateway/slash_commands.py:1019` (Discord, Telegram) | filtered list (drops providers with empty `models`) |

`list_picker_providers()` wraps `list_authenticated_providers()` and only
filters out rows where `models` is empty AND not a custom endpoint. So if
your provider is in the base list with ≥1 model, it should pass through.
**Verify both** when debugging "missing from picker":

```python
from hermes_cli.model_switch import (
    list_authenticated_providers,
    list_picker_providers,
)
base = list_authenticated_providers()
picker = list_picker_providers(max_models=50)
print('base:', [r['slug'] for r in base])
print('picker:', [r['slug'] for r in picker])
```

If `base` has it but `picker` doesn't, the model list is empty for some
reason — check `_PROVIDER_MODELS` and that the live `/v1/models` endpoint
returned rows that survived into the picker.

### The picker cache file

`~/.hermes/provider_models_cache.json` is written by the picker prewarm
thread (`prewarm_picker_cache_async`, started on gateway launch, runs once
per process). Modified time = when the prewarm last ran. If the file is
older than the latest gateway restart, the prewarm hasn't run yet — give
it ~5s after `systemctl --user start hermes-gateway`, then re-check.

```bash
stat -c '%y' ~/.hermes/provider_models_cache.json
# Compare to "Active since" from `systemctl --user status hermes-gateway`
```

### Restart recipe (safe, preserves sessions)

`hermes-gateway` has `Restart=always` in its unit, so a simple restart
just bounces the service. The systemd unit has `[Service] SendSIGKILL=no
TimeoutStopSec=120` — full graceful drain on the first SIGTERM, then
SIGKILL. Sessions are stateless (the session DB is SQLite on disk), so
users reconnect automatically.

```bash
# Hot reload (SIGHUP / SIGUSR1) does NOT reload Python modules — do not bother.
# This will say "reload" but PID stays the same and code is unchanged:
systemctl --user reload hermes-gateway

# Full restart — required after editing hermes_cli/*.py:
systemctl --user restart hermes-gateway
# Confirm new code is loaded:
systemctl --user status hermes-gateway   # check "Active since" timestamp
curl -s http://127.0.0.1:<proxy-port>/healthz  # verify your proxy still up
```

After restart, the picker prewarm thread runs once and writes
`provider_models_cache.json`. Your new provider should appear in `/model`
within ~5s. (Discord-side, the user types `/model` to trigger the picker;
no need to re-register the bot.)

### Pitfall: `cli/main.py` tests lie about the gateway

A clean `python -c "from hermes_cli.model_switch import ...; ..."` test
will ALWAYS show your new code — Python reimports on process start. This
is the trap that makes you think "the code is correct, so the picker
should work" when the gateway is still running pre-patch code. **The
relevant test is: does `/model` in Discord show the new provider?**
Not: does `list_picker_providers()` return it? Both should agree, but
only after the gateway restart.

Verification protocol (the order matters):

1. Edit `hermes_cli/providers.py` / `models.py` / `auth.py` (or just one
   if you're tightening an existing entry).
2. `systemctl --user restart hermes-gateway`.
3. Wait 5s for picker prewarm to complete.
4. Check `stat -c '%y' ~/.hermes/provider_models_cache.json` — should be
   ≤ 5s old.
5. Run the Python E2E check from a fresh `venv/bin/python -c "..."` —
   should return the new provider.
6. **Final check** (only the user can do this): type `/model` in Discord
   and confirm the picker shows the new provider.

Skip step 2 → step 5 lies to you. The user will report "still not
showing" and you'll think you missed an edit.

## See also

- `agent/gemini_native_adapter.py` — reference for the in-process OpenAI-shape facade pattern (1001 lines), useful if you need streaming / tool-calling parity beyond what a proxy gives you.
- `references/picker-e2e-verification.md` — copy-paste E2E recipe for "is my provider actually showing in the picker?" with the exact Python snippets, cache-file checks, and gateway-restart steps.
