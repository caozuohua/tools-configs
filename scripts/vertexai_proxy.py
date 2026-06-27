#!/usr/bin/env python3
"""Vertex AI Gemini proxy — OpenAI-shape HTTP frontend over google-genai.

Listens on http://127.0.0.1:18999/v1/chat/completions and translates each
incoming OpenAI-shape request to a google-genai (Vertex AI) call. Lets
Hermes use Vertex AI / Gemini models via the existing ``openai_chat``
transport — no Hermes core changes needed; just register a provider with
``base_url=http://127.0.0.1:18999/v1``.

Why a proxy (vs a full in-process OpenAI-shape adapter)?
- ~200 lines vs ~600 for the in-process equivalent
- Independently testable with curl before wiring into Hermes
- Zero Hermes core changes — survives upstream upgrades cleanly
- Auth: gcloud ADC auto-refresh (no Bearer token churn)

Run modes:
    # foreground (dev)
    python3 vertexai_proxy.py

    # background (production)
    python3 vertexai_proxy.py &

    # systemd (preferred; see vertexai_proxy.service in this dir)

Env vars:
    VERTEXAI_PROXY_HOST      (default: 127.0.0.1)
    VERTEXAI_PROXY_PORT      (default: 18999)
    GOOGLE_CLOUD_PROJECT     (default: project-c1ed131b-6f02-49de-9f8)
    GOOGLE_CLOUD_LOCATION    (default: global)
    VERTEXAI_MAX_OUTPUT      (default: 8192)

Dependencies (already in hermes venv):
    google-genai>=2.9.0     (uses gcloud ADC automatically)

Endpoints:
    GET  /healthz                    -> 200 OK with project + location
    GET  /v1/models                  -> OpenAI-shape list (handful of Gemini IDs)
    POST /v1/chat/completions        -> OpenAI-shape chat completion (incl. stream)
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# Global thought_signature cache: {tool_call_id: signature_bytes}
# Survives across requests within the same proxy process.
# In multi-turn tool calling, Hermes may fail to replay extra_content on
# the assistant message. The proxy caches the signature from the first
# response and injects it into subsequent requests automatically.
_THOUGHT_SIG_CACHE: dict[str, bytes] = {}

DEFAULT_PROJECT = "project-c1ed131b-6f02-49de-9f8"
DEFAULT_LOCATION = "global"

# Curated model list — matches nanobot vps-lite verified set + a few siblings.
# Picked from what's known to actually return responses against this project.
DEFAULT_MODELS = [
    "gemini-2.5-pro",          # us-central1 + global
    "gemini-3.5-flash",         # global only
    "gemini-3.1-flash-lite",   # global only
    "gemini-3-flash-preview",  # global only
    "gemini-flash-latest",     # global only
]


def _project() -> str:
    return os.environ.get("GOOGLE_CLOUD_PROJECT", DEFAULT_PROJECT)


def _location() -> str:
    return os.environ.get("GOOGLE_CLOUD_LOCATION", DEFAULT_LOCATION)


def _max_output() -> int:
    try:
        return int(os.environ.get("VERTEXAI_MAX_OUTPUT", "8192"))
    except Exception:
        return 8192


def _genai_client():
    """Lazy import + client factory — picks up gcloud ADC automatically."""
    from google import genai  # noqa: WPS433 (intentional lazy import)
    return genai.Client(vertexai=True, project=_project(), location=_location())


# ----- OpenAI -> Gemini translation ------------------------------------------

def _decode_thought_signature(tool_call: dict) -> bytes | None:
    """Extract + base64-decode Gemini thought_signature from an OpenAI tool_call dict.

    Hermes passes ``extra_content.google.thought_signature`` through unchanged
    on its Gemini-family targets (see run_agent._sanitize_tool_calls_for_strict_api +
    chat_completions._model_consumes_thought_signature). When present, the
    signature MUST be replayed on the next request, otherwise Gemini 3.x
    rejects with 400 "Function call is missing a thought_signature".

    Returns ``None`` if the field is missing or malformed; callers should
    still send the request and let the model reject if the signature is truly
    required and absent (some Gemini variants only enforce on multi-turn).
    """
    extra = tool_call.get("extra_content")
    if not isinstance(extra, dict):
        return None
    google = extra.get("google")
    if not isinstance(google, dict):
        return None
    sig = google.get("thought_signature")
    if not isinstance(sig, str) or not sig:
        return None
    try:
        import base64 as _b64
        return _b64.b64decode(sig, validate=True)
    except Exception:
        return None


def _to_gemini_contents(messages: list[dict]) -> tuple[list[dict], str | None]:
    """Convert OpenAI messages[] to Gemini contents[] + extracted system instruction.

    OpenAI roles: system | user | assistant | tool
    Gemini roles:  user | model (function_response parts attach to a user turn)

    Key fixes vs naive translation (validated against Vertex AI 3.x):
    - Tool results use ``role: "user"`` with a ``function_response`` part, NOT
      ``role: "function"`` — the latter is silently dropped / 400'd.
    - Empty content parts are replaced with a "." placeholder; Vertex AI
      rejects ``parts: []`` with "Model input cannot be empty".
    - Assistant messages with tool_calls + null content produce ``parts``
      containing only the function_call (no empty text part).
    - ``extra_content.google.thought_signature`` from a prior turn is
      re-attached to each ``function_call`` part as binary ``thought_signature``.
    """
    import base64 as _b64

    system_text: str | None = None
    contents: list[dict] = []

    # Buffer tool responses so we can attach them to the previous user turn,
    # matching nanobot's pattern when multiple tool results follow one tool call.
    pending_tool_results: list[dict] = []

    def _flush_tool_results() -> None:
        nonlocal pending_tool_results
        if pending_tool_results:
            contents.append({"role": "user", "parts": pending_tool_results})
            pending_tool_results = []

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        if role == "system":
            text = content if isinstance(content, str) else ""
            system_text = (system_text + "\n\n" + text) if system_text else text
            continue

        if role == "user":
            _flush_tool_results()
            if isinstance(content, str):
                # Empty string -> Vertex AI rejects with "Model input cannot be empty".
                # Use a placeholder that the model will treat as a no-op text part.
                parts = [{"text": content or "."}]
            elif isinstance(content, list):
                parts = content or [{"text": "."}]
            else:
                parts = [{"text": str(content) if content is not None else "."}]
            contents.append({"role": "user", "parts": parts})
            continue

        if role == "assistant":
            _flush_tool_results()
            parts: list[dict] = []
            tool_calls = msg.get("tool_calls") or []
            if content and not tool_calls:
                if isinstance(content, str):
                    parts.append({"text": content})
                else:
                    parts.append({"text": json.dumps(content, ensure_ascii=False)})
            elif content and tool_calls:
                parts.append({"text": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)})
            for tc in tool_calls:
                fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                args = fn.get("arguments", "")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}
                fc_part: dict = {"function_call": {"name": fn.get("name", ""), "args": args or {}}}
                # Replay thought_signature: first try from the incoming
                # extra_content (Hermes may or may not have preserved it),
                # then fall back to the proxy-level cache.
                sig_bytes = _decode_thought_signature(tc) if isinstance(tc, dict) else None
                if not sig_bytes:
                    tc_id = tc.get("id") if isinstance(tc, dict) else None
                    if tc_id and tc_id in _THOUGHT_SIG_CACHE:
                        sig_bytes = _THOUGHT_SIG_CACHE[tc_id]
                if sig_bytes:
                    fc_part["thought_signature"] = sig_bytes
                parts.append(fc_part)
            if not parts:
                continue
            contents.append({"role": "model", "parts": parts})
            continue

        if role == "tool":
            fn_name = msg.get("name", "unknown_tool")
            payload = content if isinstance(content, str) else json.dumps(content or {})
            # Gemini wants tool results as user-role messages with function_response parts.
            pending_tool_results.append({
                "function_response": {"name": fn_name, "response": {"result": payload}},
            })
            continue

        # Unknown role — best-effort pass-through as user text.
        _flush_tool_results()
        parts = [{"text": str(content) if content is not None else "."}]
        contents.append({"role": "user", "parts": parts})

    _flush_tool_results()
    return contents, system_text


def _to_gemini_tools(tools: list[dict] | None) -> list[dict] | None:
    """Convert OpenAI tools[] to Gemini function_declarations."""
    if not tools:
        return None
    declarations = []
    for tool in tools:
        if tool.get("type") != "function":
            continue
        fn = tool.get("function", {})
        declarations.append({
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return [{"function_declarations": declarations}] if declarations else None


def _to_gemini_tool_config(tool_choice: Any) -> dict | None:
    """Convert OpenAI tool_choice to Gemini tool_config."""
    if not tool_choice:
        return None
    if isinstance(tool_choice, str):
        if tool_choice == "none":
            return {"function_calling_config": {"mode": "NONE"}}
        if tool_choice == "auto":
            return {"function_calling_config": {"mode": "AUTO"}}
        if tool_choice == "required":
            return {"function_calling_config": {"mode": "ANY"}}
    if isinstance(tool_choice, dict):
        fn = tool_choice.get("function", {})
        if fn.get("name"):
            return {"function_calling_config": {"mode": "ANY", "allowed_function_names": [fn["name"]]}}
    return None


def _extract_text_and_tool_calls(resp: Any) -> tuple[str, list[dict], str]:
    """Pull text + tool calls + finish_reason out of a google-genai response.

    Avoids ``resp.text`` because that getter emits a stderr Warning whenever
    the response also has ``function_call`` parts. Iterating parts directly
    is the canonical pattern and is warning-free.

    Captures each ``function_call`` part's ``thought_signature`` (binary
    blob from Gemini 3.x) and embeds it as ``extra_content.google.thought_signature``
    (base64 string) on the OpenAI tool_call. Hermes replays this field on the
    next request to the same provider — without it, Gemini rejects the
    resend with HTTP 400.
    """
    import base64 as _b64

    text_parts: list[str] = []
    tool_calls: list[dict] = []
    raw_finish = ""

    candidates = getattr(resp, "candidates", None) or []
    if candidates:
        cand = candidates[0]
        raw = getattr(cand, "finish_reason", None)
        if raw is not None:
            raw_finish = str(raw).upper()

        content = getattr(cand, "content", None)
        if content is not None:
            for part in (getattr(content, "parts", None) or []):
                # Text part
                ptxt = getattr(part, "text", None)
                if ptxt:
                    text_parts.append(ptxt)
                    continue
                # Function-call part
                fc = getattr(part, "function_call", None)
                if fc is not None:
                    name = getattr(fc, "name", "") or ""
                    args = getattr(fc, "args", None) or {}
                    tc: dict = {
                        "id": f"call_{uuid.uuid4().hex[:24]}",
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(args, ensure_ascii=False),
                        },
                    }
                    # Capture thought_signature so multi-turn tool calling works.
                    sig = getattr(part, "thought_signature", None)
                    if isinstance(sig, (bytes, bytearray)) and sig:
                        tc["extra_content"] = {
                            "google": {
                                "thought_signature": _b64.b64encode(bytes(sig)).decode("ascii"),
                            }
                        }
                    tool_calls.append(tc)
                    continue
                # Thought part (thinking): skip silently; Gemini sometimes
                # includes a "thought" marker on parts that has no text.

    text = "".join(text_parts)
    return text, tool_calls, raw_finish


def _cache_thought_signatures(tool_calls: list[dict]) -> None:
    """Cache thought_signatures from model response for later replay.

    Called after _extract_text_and_tool_calls to populate the global cache
    keyed by tool_call id. On the next request, _inject_cached_signatures
    will restore them if Hermes failed to replay extra_content.
    """
    import base64 as _b64
    for tc in tool_calls:
        tc_id = tc.get("id")
        if not tc_id:
            continue
        extra = tc.get("extra_content")
        if not isinstance(extra, dict):
            continue
        sig_b64 = extra.get("google", {}).get("thought_signature")
        if not isinstance(sig_b64, str) or not sig_b64:
            continue
        try:
            _THOUGHT_SIG_CACHE[tc_id] = _b64.b64decode(sig_b64, validate=True)
        except Exception:
            pass


def _normalize_finish_reason(raw_finish: str, has_tool_calls: bool) -> str:
    """Map Gemini finish reason to OpenAI shape (or pick tool_calls priority)."""
    if has_tool_calls:
        return "tool_calls"
    if "MAX_TOKEN" in raw_finish:
        return "length"
    if raw_finish in {"SAFETY", "RECITATION", "BLOCKLIST",
                      "PROHIBITED_CONTENT", "SPII"}:
        return "content_filter"
    # STOP and unknown values both map to "stop" — be lenient on new reasons.
    return "stop"


def _gemini_to_openai_response(resp: Any, model: str, created: int) -> dict:
    """Translate google-genai response to OpenAI chat.completion shape."""
    text, tool_calls, raw_finish = _extract_text_and_tool_calls(resp)
    # Cache thought_signatures so we can inject them on the next request
    # even if Hermes fails to replay extra_content on the assistant message.
    if tool_calls:
        _cache_thought_signatures(tool_calls)
    finish_reason = _normalize_finish_reason(raw_finish, bool(tool_calls))

    usage = getattr(resp, "usage_metadata", None)
    usage_dict = None
    if usage is not None:
        try:
            usage_dict = usage.model_dump(exclude_none=True)
        except Exception:
            try:
                usage_dict = dict(usage)
            except Exception:
                usage_dict = None

    # OpenAI convention: when the assistant message has tool_calls, content is null
    # (not ""). Strict clients (incl. Hermes) validate this. nanobot follows the same rule.
    message: dict[str, Any]
    if tool_calls:
        message = {"role": "assistant", "content": None, "tool_calls": tool_calls}
    else:
        message = {"role": "assistant", "content": text}

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": finish_reason,
        }],
        "usage": usage_dict,
    }


def _gemini_stream_chunk_dict(model: str, created: int, delta: dict, finish_reason: str | None) -> dict:
    """Build an OpenAI-shape streaming chunk from an arbitrary delta dict.

    Delta shape follows OpenAI conventions:
    - Text: ``{"role": "assistant", "content": "<delta text>"}``
    - Tool calls: ``{"role": "assistant", "content": null, "tool_calls": [...]}``
    - Final: ``{}`` with ``finish_reason`` set in the choice.
    """
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{
            "index": 0,
            "delta": delta,
            "finish_reason": finish_reason,
        }],
    }


# ----- HTTP handler -----------------------------------------------------------

class VertexAIProxyHandler(BaseHTTPRequestHandler):
    server_version = "VertexAIProxy/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), format % args))

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self._send_json(200, {
                "status": "ok",
                "project": _project(),
                "location": _location(),
                "models": DEFAULT_MODELS,
            })
            return
        if path == "/v1/models":
            self._send_json(200, {
                "object": "list",
                "data": [
                    {"id": m, "object": "model", "created": int(time.time()), "owned_by": "google"}
                    for m in DEFAULT_MODELS
                ],
            })
            return
        self._send_json(404, {"error": {"message": f"not found: {path}", "type": "invalid_request_error"}})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path != "/v1/chat/completions":
            self._send_json(404, {"error": {"message": f"not found: {path}", "type": "invalid_request_error"}})
            return

        try:
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length) if length > 0 else b""
            req = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as exc:
            self._send_json(400, {"error": {"message": f"bad request: {exc}", "type": "invalid_request_error"}})
            return

        model = req.get("model") or DEFAULT_MODELS[0]
        # Strip provider prefix so Vertex AI receives a bare model id.
        # Handles both colon-separated (vertexai:gemini-3.5-flash) and
        # slash-separated (vertexai/gemini-3.5-flash) formats.
        _PREFIXES = ("vertexai", "vertex", "vertex-ai", "vertexai-genai")
        if ":" in model:
            _prefix, _, _rest = model.partition(":")
            if _prefix.lower() in _PREFIXES:
                model = _rest
        elif "/" in model:
            _prefix, _, _rest = model.partition("/")
            if _prefix.lower() in _PREFIXES:
                model = _rest
        messages = req.get("messages") or []  # do NOT mutate caller's list
        tools = req.get("tools")
        tool_choice = req.get("tool_choice")
        stream = bool(req.get("stream"))
        # OpenAI clients send max_tokens or max_completion_tokens; clamp to >=1
        # (Gemini rejects max_output_tokens<=0 with 400 INVALID_ARGUMENT).
        raw_max = req.get("max_tokens") or req.get("max_completion_tokens")
        try:
            max_tokens = max(1, int(raw_max)) if raw_max is not None else _max_output()
        except Exception:
            max_tokens = _max_output()
        temperature = req.get("temperature")
        created = int(time.time())

        try:
            contents, system_text = _to_gemini_contents(messages)
            gemini_tools = _to_gemini_tools(tools)
            gemini_tool_config = _to_gemini_tool_config(tool_choice)
        except Exception as exc:
            self._send_json(400, {"error": {"message": f"request translation failed: {exc}", "type": "invalid_request_error"}})
            return

        config: dict[str, Any] = {"max_output_tokens": int(max_tokens)}
        if system_text:
            config["system_instruction"] = system_text
        if gemini_tools:
            config["tools"] = gemini_tools
        if gemini_tool_config:
            config["tool_config"] = gemini_tool_config
        if temperature is not None:
            config["temperature"] = float(temperature)

        client = _genai_client()

        if stream:
            # Streaming SSE response (OpenAI delta shape)
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()

                import base64 as _stream_b64
                accum_text = ""
                accum_tool_calls: list[dict] = []

                for chunk in client.models.generate_content_stream(
                    model=model,
                    contents=contents,
                    config=config,
                ):
                    chunk_text = ""
                    chunk_tool_calls: list[dict] = []
                    chunk_finish = None
                    for part in (getattr(getattr(chunk, "candidates", [None])[0], "content", None) and
                                 getattr(getattr(chunk.candidates[0], "content", None), "parts", None) or []):
                        ptxt = getattr(part, "text", None)
                        if ptxt:
                            chunk_text += ptxt
                        fc = getattr(part, "function_call", None)
                        if fc is not None:
                            name = getattr(fc, "name", "") or ""
                            args = getattr(fc, "args", None) or {}
                            tc_dict = {
                                "id": f"call_{uuid.uuid4().hex[:24]}",
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": json.dumps(args, ensure_ascii=False),
                                },
                            }
                            # Capture thought_signature from streaming chunk if present.
                            sig = getattr(part, "thought_signature", None)
                            if isinstance(sig, (bytes, bytearray)) and sig:
                                tc_dict["extra_content"] = {
                                    "google": {
                                        "thought_signature": _stream_b64.b64encode(bytes(sig)).decode("ascii"),
                                    }
                                }
                            chunk_tool_calls.append(tc_dict)

                    if chunk_text:
                        accum_text += chunk_text
                        delta = {"role": "assistant", "content": chunk_text}
                        sse = f"data: {json.dumps(_gemini_stream_chunk_dict(model, created, delta, None), ensure_ascii=False)}\n\n"
                        self.wfile.write(sse.encode("utf-8"))
                        self.wfile.flush()
                    if chunk_tool_calls:
                        accum_tool_calls.extend(chunk_tool_calls)

                # Final chunk — emit accumulated tool_calls and cache signatures.
                final_delta: dict[str, Any] = {}
                if accum_tool_calls:
                    _cache_thought_signatures(accum_tool_calls)
                    final_delta["tool_calls"] = accum_tool_calls
                    final_delta["content"] = None
                final = _gemini_stream_chunk_dict(
                    model, created, final_delta,
                    "tool_calls" if accum_tool_calls else "stop",
                )
                self.wfile.write(f"data: {json.dumps(final, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except Exception as exc:
                err = json.dumps({"error": {"message": str(exc), "type": "server_error"}}).encode("utf-8")
                try:
                    self.wfile.write(f"data: {err.decode('utf-8')}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except Exception:
                    pass
            return

        # Non-streaming response
        try:
            resp = client.models.generate_content(model=model, contents=contents, config=config)
        except Exception as exc:
            self._send_json(502, {"error": {"message": f"vertex ai error: {exc}", "type": "server_error"}})
            return

        self._send_json(200, _gemini_to_openai_response(resp, model, created))


def main() -> int:
    host = os.environ.get("VERTEXAI_PROXY_HOST", "127.0.0.1")
    port = int(os.environ.get("VERTEXAI_PROXY_PORT", "18999"))

    # Eager-fail if the genai library is missing
    try:
        import google.genai  # noqa: F401
    except ImportError:
        print(
            "google-genai not installed. Run:\n"
            "  /home/caozuohua99/.hermes/hermes-agent/venv/bin/pip install google-genai==2.9.0",
            file=sys.stderr,
        )
        return 2

    httpd = ThreadingHTTPServer((host, port), VertexAIProxyHandler)
    print(
        f"vertexai_proxy listening on http://{host}:{port}/  "
        f"project={_project()} location={_location()} models={DEFAULT_MODELS}",
        file=sys.stderr,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
