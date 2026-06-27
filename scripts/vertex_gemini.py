#!/usr/bin/env python3
"""Side-channel wrapper around Google Vertex AI Gemini via the genai library.

Uses caozuohua99's gcloud ADC (Application Default Credentials) — no service
account JSON file needed. Same project/location/model combo that's verified
working on nanobot's vps-lite profile (2026-06-20):

  project=project-c1ed131b-6f02-49de-9f8
  location=global
  model=gemini-3.1-flash-lite

Usage:
    venv/bin/python3 ~/.hermes/scripts/vertex_gemini.py "Your prompt here"
    echo "Your prompt" | venv/bin/python3 ~/.hermes/scripts/vertex_gemini.py -

Output: JSON {"text": "...", "usage": {...}, "model": "..."} on stdout.

Env vars (override defaults):
    GOOGLE_CLOUD_PROJECT  (default: project-c1ed131b-6f02-49de-9f8)
    GOOGLE_CLOUD_LOCATION (default: global)
    GEMINI_MODEL          (default: gemini-3.1-flash-lite)
    GEMINI_MAX_TOKENS     (default: 1024)

Why a side-channel script (not a Hermes provider):
- Lowest-risk: doesn't touch Hermes core, survives upstream upgrades.
- Hermes currently ships `gemini` (AI Studio) and `google-gemini-cli` (Cloud
  Code Assist) providers, but no Vertex AI / genai provider. Adding one is a
  Hermes core change (touches agent_runtime_helpers.py + config schema +
  model registration). That's a separate, bigger piece of work.
- This script gives us a working tool now, so we can decide later if a full
  provider integration is worth the maintenance burden.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

DEFAULT_PROJECT = "project-c1ed131b-6f02-49de-9f8"
DEFAULT_LOCATION = "global"
DEFAULT_MODEL = "gemini-3.1-flash-lite"


def _read_prompt(argv: list[str]) -> str:
    if len(argv) < 2:
        print("usage: vertex_gemini.py <prompt> | -", file=sys.stderr)
        sys.exit(2)
    if argv[1] == "-":
        return sys.stdin.read()
    return " ".join(argv[1:])


def _usage_to_dict(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    try:
        # google-genai returns a UsageMetadata pydantic model
        return usage.model_dump(exclude_none=True)
    except Exception:
        try:
            return dict(usage)
        except Exception:
            return None


def main() -> int:
    prompt = _read_prompt(sys.argv)
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", DEFAULT_PROJECT)
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", DEFAULT_LOCATION)
    model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    max_tokens = int(os.environ.get("GEMINI_MAX_TOKENS", "1024"))

    # Lazy import so the script's --help-style failure mode is fast
    from google import genai  # noqa: WPS433 (intentional lazy import)

    client = genai.Client(vertexai=True, project=project, location=location)
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config={"max_output_tokens": max_tokens},
    )

    out = {
        "text": resp.text or "",
        "model": model,
        "project": project,
        "location": location,
        "usage": _usage_to_dict(getattr(resp, "usage_metadata", None)),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
