---
name: hermes-vertexai-provider
description: "Wire Google Vertex AI / Gemini into Hermes as a provider via the OpenAI-shape HTTP proxy at ~/.hermes/scripts/vertexai_proxy.py (127.0.0.1:18999). Covers the 5 known 400 INVALID_ARGUMENT bugs (thought_signature, role mapping, empty parts, max_output_tokens, vertexai: prefix), the proxy-level thought_signature cache that auto-injects missing signatures on multi-turn tool calls, the nanobot VertexAIProvider reference, and Hermes's _sanitize_tool_calls_for_strict_api / _model_consumes_thought_signature conventions. Trigger: integrating vertexai/gemini into Hermes, debugging OpenAI-shape↔Gemini 400s, thought_signature round-trip failures, or extending the proxy."
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [vertexai, gemini, hermes, provider, proxy, openai-shape, google-cloud, thought-signature]
    trigger: "When working with Vertex AI / Gemini in Hermes — wiring, debugging 400 INVALID_ARGUMENT, thought_signature issues, or extending the OpenAI-shape proxy"
---

# Hermes Vertex AI Provider Integration

## Context (gcp-vps2, validated 2026-06-21)

Two parallel Vertex AI deployments exist on `gcp-vps2`:

- **nanobot** at `/opt/nanobot/nanobot/providers/vertex_ai_provider.py` — uses `google-genai` directly via ADC. **Gold reference** for the OpenAI↔Gemini protocol.
- **Hermes** at `~/.hermes/scripts/vertexai_proxy.py` — OpenAI-shape HTTP proxy on 127.0.0.1:18999, backend = `google-genai`. Registered as the `vertexai` provider in `hermes_cli/{auth,models,providers}.py`. Models: `gemini-3.1-flash-lite`, `gemini-3-flash-preview`, `gemini-flash-latest`.

This skill covers the **Hermes** path. Cross-reference nanobot's `VertexAIProvider` (387 lines, well-tested) whenever protocol behavior is ambiguous.

## Architecture: Proxy vs In-Process Adapter

| Aspect | Proxy (current) | In-Process Adapter |
|--------|-----------------|-------------------|
| Code size | ~330 lines | ~600 lines |
| Hermes core changes | 4 patches (PROVIDER_REGISTRY, _PROVIDER_MODELS, HERMES_OVERLAYS, .env) | 0 (provider.py) |
| gcloud ADC | Yes (auto-refresh) | Yes |
| Survives upstream sync | Yes (config-only) | Yes (still pure) |
| Latency | +1 HTTP hop on loopback | None |
| Debugging | curl-able independently | Inside venv |
| Recommended for | Initial wiring, iteration | Future if proxy becomes a bottleneck |

**Proxy is preferred** — per the AGENTS.md contribution rubric, capability at the edges via provider registration, not in the core.

## Protocol Translation: OpenAI ↔ Gemini

The full mapping table is in `references/vertexai-protocol.md`. The four most-surprising translation rules (each one a 400 bug that shipped):

1. **thought_signature round-trip** — Gemini 3.x attaches a binary blob to every `function_call` part it generates. The next turn MUST replay it or Gemini 400s with "Function call is missing a thought_signature in functionCall parts". OpenAI shape has no native field → convention is `extra_content.google.thought_signature` (base64). Hermes preserves this field when target model is Gemini-family (`run_agent.py:4991 _sanitize_tool_calls_for_strict_api` strips it for non-Gemini). The proxy MUST capture on response + replay on request.
2. **Tool result role** = `user` (NOT `function`) with a `function_response` part. Naive `role: "function"` is silently dropped.
3. **Empty parts** → 400 "Model input cannot be empty". Use `"."` placeholder for empty user text.
4. **Empty assistant + tool_calls** = `parts` with function_call only, no empty text part.
5. **`max_output_tokens`** must be `>= 1`. Clamp in proxy (`max(1, int(raw_max))`).
6. **`vertexai:` and `vertexai/` prefix stripping** — Hermes may send `vertexai:gemini-3.5-flash` (colon) or `vertexai/gemini-3.5-flash` (slash). The proxy must strip both. Only the colon variant was handled before 2026-06-23; the slash variant caused 404 NOT_FOUND.

## Working Models (gcp-vps2 project `project-c1ed131b-6f02-49de-9f8`)

| Model | location | Status |
|-------|----------|--------|
| `gemini-2.5-pro` | `us-central1` or `global` | ⚠️ 429 RESOURCE_EXHAUSTED (quota exceeded on project `project-c1ed131b-6f02-49de-9f8`). Use `gemini-3.5-flash` as fallback |
| `gemini-3.5-flash` | `global` | ✅ works (recommended default) |
| `gemini-3.1-flash-lite` | `global` | ✅ works, default |
| `gemini-3-flash-preview` | `global` | ✅ works |
| `gemini-flash-latest` | `global` | ✅ works |
| `gemini-2.0-flash`, `gemini-1.5-flash` | — | ❌ 404 |
| `gemini-2.5-pro-preview-06-05` | — | ❌ 404 (preview snapshot, superseded) |

Gemini 3.x family **requires** `GOOGLE_CLOUD_LOCATION=global` (NOT `us-central1`).
Gemini 2.5+ are "thinking" models — `max_tokens` budget splits between `thoughts_token_count` and `candidates_token_count`. Live-test with `max_tokens=200+` to see actual text (default `VERTEXAI_MAX_OUTPUT=8192` is fine for real use). At `max_tokens=20` the proxy returns HTTP 200 with `content=""` and `finish_reason="length"` because the entire budget went to thinking — this is **not** a proxy bug.

> Earlier versions of this SKILL said `gemini-3.5-flash` was ❌ due to a TypeError SDK bug at small `max_output_tokens`. Live ping on 2026-06-21 with `max_tokens=200` returned `{"content":"OK.","finish_reason":"stop"}` HTTP 200 from the proxy — works fine. Status updated to ✅. The earlier ❌ was likely an SDK bug fixed in google-genai 2.9.0, or a transient failure mode.

## How to Debug a New 400 INVALID_ARGUMENT

**Step 0 (pre-flight)**: Before touching the proxy, verify the failing
call actually went to vertexai — see `references/troubleshooting.md`
"Pre-flight" section. Users switch models between the error and the
report; "gemini 400" is often a historical artifact when the active
provider is now something else (e.g. MiniMax-M3 via tokenrouter).

1. Add `sys.stderr.write(f"DEBUG REQUEST: {json.dumps(req)[:3000]}\n"); sys.stderr.flush()` after the request parse in `do_POST`, `systemctl --user restart vertexai_proxy`.
2. Tail journal: `journalctl --user -u vertexai_proxy -n 30 --no-pager`.
3. Reproduce with `curl` or the verification script.
4. Match error to one of the 5 bugs in `references/troubleshooting.md`.
5. Patch `vertexai_proxy.py`, `systemctl --user restart vertexai_proxy`, remove debug line.

## Files

- **Proxy**: `~/.hermes/scripts/vertexai_proxy.py`
- **Systemd unit**: `~/.config/systemd/user/vertexai_proxy.service`
- **Hermes patches**: `hermes_cli/{auth,models,providers}.py` — search "vertexai"
- **.env additions**: `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION=global`, `VERTEXAI_PROXY_URL=http://127.0.0.1:18999/v1`, `VERTEXAI_PROXY_KEY=<any-string>`
- **ADC credentials**: `gcloud auth application-default login` as `caozuohua99` (or use service-account path per nanobot's `nanobot.env`)

## Verification Recipe

```bash
# 1. Sanity
curl -s http://127.0.0.1:18999/healthz | jq

# 2. Simple text (must return 200)
curl -s -X POST http://127.0.0.1:18999/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"gemini-3.1-flash-lite","messages":[{"role":"user","content":"Just OK."}],"max_tokens":50}' | jq

# 3. Full E2E (multi-turn tool call, all 3 models, edge cases)
python3 ~/.hermes/skills/hermes-vertexai-provider/scripts/test-vertexai-proxy.py
```

## Rollback

```bash
systemctl --user disable --now vertexai_proxy
# Remove 4 lines from hermes_cli/{auth,models,providers}.py (search "vertexai")
# Remove 4 lines from ~/.hermes/.env
rm ~/.hermes/scripts/vertexai_proxy.py ~/.config/systemd/user/vertexai_proxy.service
```

## Diagnostic Flow: "Proxy Healthy but Tools Don't Work"

When the user reports "只能打招呼，无法调用工具" (can only chat, can't call tools), the symptom almost always means the proxy is fine but **Hermes is not actually routing to the proxy**. Verified 2026-06-23: proxy returned correct `tool_calls` with `thought_signature` on curl test, but Hermes was using `openrouter/owl-alpha` as provider — not vertexai at all.

**Step-by-step diagnosis:**

1. **Confirm proxy is alive** — `curl -s http://127.0.0.1:18999/healthz` → must return `{"status":"ok"}`
2. **Confirm proxy handles tools** — `curl -s -X POST http://127.0.0.1:18999/v1/chat/completions -H 'Content-Type: application/json' -d '{"model":"gemini-3.5-flash","messages":[{"role":"user","content":"use tool"}],"tools":[...]}'` → must return `tool_calls` in response
3. **Check hermes actual provider** — `cat ~/.hermes/config.yaml | grep -E "^model:|provider:"` → if it shows `openrouter/owl-alpha` (or anything non-vertexai), that's the problem
4. **Fix**: Add vertexai to `custom_providers` in `~/.hermes/config.yaml` OR switch `model.provider` to the vertexai custom provider name

**Root cause patterns:**
- Provider config changed (e.g. during migration or setup) but proxy left running
- `custom_providers` block missing the vertexai entry
- `model.default` points to a model name that doesn't match any configured provider

## Pitfalls (gcp-vps2 / 2026-06-23)

- **Don't reinvent the proxy.** Before suggesting "set up a Vertex AI proxy / LiteLLM / Codex → Gemini bridge", check whether `~/.hermes/scripts/vertexai_proxy.py` and `systemctl --user status vertexai_proxy` already exist. If the proxy is already wired (it usually is on gcp-vps2), the right move is patch `DEFAULT_MODELS` + `systemctl --user restart vertexai_proxy`. The proxy was built specifically to avoid re-implementing OpenAI↔Gemini translation in Hermes core — every layer of the problem (auth, model list, thought_signature, role mapping) was already solved.
- **Don't ask A/B/C option trees when the user is time-pressured.** When the user gives a deadline ("X 马上到期了"), load the relevant skill first, do one audit pass (✓/✗), then ONE fix per turn. Asking "走 A 还是 B 还是 C?" is the wrong shape — the user pushed back with "你回忆下我们到底在干嘛". The correct flow: probe what exists → patch what's needed → report.
- **Always do the live pre-flight before debugging a Gemini 400.** Confirm the failing call actually went to vertexai (curl `http://127.0.0.1:18999/v1/models` and `tail journalctl --user -u vertexai_proxy`). Historical errors get copy-pasted into new tickets even after the user switched to a different provider — same symptom, different cause.
- **gcloud ADC is enough — don't insist on SA JSON path.** `google-genai` SDK auto-picks up `~/.config/gcloud/application_default_credentials.json` when `GOOGLE_APPLICATION_CREDENTIALS` is unset. Don't ask "where do I put the SA JSON?" unless the user actually wants to harden against ADC rotation. ADC project has been `project-c1ed131b-6f02-49de-9f8` since 2026-06-21.
- **Gemini 3.x thinking mode eats output tokens (validated 2026-06-26):** When using the proxy via OpenAI-compatible SDK (e.g. `openai` Python package), Gemini 3.x models default to "thinking" mode where `thoughts_token_count` consumes most of the `max_tokens` budget. At `max_tokens=50` the response is `content=""` with `finish_reason="length"` — NOT a proxy bug. **Fix:** pass `extra_body={"google": {"thinking_config": {"include_thoughts": False, "thinking_budget": 0}}}` AND set `max_tokens=20048` (not 500). Verified: with thinking disabled, `gemini-3.5-flash` returns full content at `max_tokens=2048`. Without this flag, even `max_tokens=100` returns empty. Available models via `/v1/models`: `gemini-2.5-pro`, `gemini-3.5-flash`, `gemini-3.1-flash-lite`, `gemini-3-flash-preview`, `gemini-flash-latest`.
- **thought_signature 400 — proxy layer cache injects automatically (2026-06-23 fix)**: The proxy now maintains a process-level `_THOUGHT_SIG_CACHE` dict keyed by `tool_call_id`. On the first response, it caches each tool_call's `thought_signature`. On subsequent requests, if Hermes sends an assistant message with tool_calls that lack `extra_content`, the proxy automatically injects the cached signature before forwarding to Vertex AI. This means the "thought_signature missing" 400 is now handled at the proxy layer — no Hermes core changes needed. If you still see this error after the fix is deployed, the cause is almost certainly that Hermes is NOT routing to the proxy at all (see pre-flight checks above). To verify the cache is working: send a multi-turn tool call via curl with `extra_content` stripped from the assistant message — the proxy should still return 200.

## References

- `references/vertexai-protocol.md` — OpenAI ↔ Gemini translation table (request + response shape)
- `references/troubleshooting.md` — 5 known 400 bugs with error transcripts and fix diffs
- `references/vertex-live-ping-recipe.md` — pre-flight model availability check (Python + curl) before adding a model to `DEFAULT_MODELS`
- `references/request-dump-debugging.md` — reading `~/.hermes/sessions/request_dump_*.json` to diagnose where `extra_content` gets lost in the message chain, and verifying the proxy-level thought_signature cache
- `scripts/test-vertexai-proxy.py` — E2E verification (multi-turn tool call, all models, edge cases)
- `/opt/nanobot/nanobot/providers/vertex_ai_provider.py` — gold reference implementation, 387 lines
