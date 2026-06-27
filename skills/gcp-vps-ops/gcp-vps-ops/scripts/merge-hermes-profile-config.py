#!/usr/bin/env python3
"""
Merge specific YAML config blocks from a source Hermes profile's
config.yaml into a target profile's config.yaml, preserving the
target's per-profile overrides.

Use case: you added `Environment=HERMES_HOME=~/.hermes-lite` to the
hermes-lite systemd unit, but `~/.hermes-lite/config.yaml` is a slim
override that lacks the model block from `~/.hermes/config.yaml`. The
gateway boots, connects to Lark, and only fails on the first LLM call
with "Primary provider auth failed". This script fixes that by overlaying
the LLM provider blocks from main into lite, keeping lite's memory /
toolsets / platform_toolsets overrides intact.

Default behavior:
  - Source: /home/<user>/.hermes/config.yaml
  - Target: /home/<user>/.hermes-lite/config.yaml
  - Overlaid blocks: model, providers, fallback_providers,
    custom_providers, credential_pool_strategies, model_catalog
  - For `model`, target's per-key sub-values WIN for keys the source
    doesn't define (so lite's `context_length: 65536` survives).
  - Backup: <target>.bak-pre-merge-<UTC-ts> (mode 0600 preserved)
  - Result written mode 0600.

Usage:
  python3 merge-hermes-profile-config.py [--src PATH] [--dst PATH]
                                          [--blocks k1,k2,...]
                                          [--dry-run]

The script does NOT restart the service. After merge, run:
  sudo systemctl restart <hermes-unit>
or just send a DM to verify Hermes re-reads config on next call.

Safe to re-run: if all overlaid blocks are already present and equal,
the file is rewritten only if something actually changed.
"""
import argparse
import os
import shutil
import sys
from datetime import datetime, timezone

# Defaults assume the standard main + lite profile layout on this user's
# gcp-vps2 setup. Override with --src / --dst for other topologies.
DEFAULT_SRC = "/home/caozuohua99/.hermes/config.yaml"
DEFAULT_DST = "/home/caozuohua99/.hermes-lite/config.yaml"
DEFAULT_BLOCKS = [
    "model",
    "providers",
    "fallback_providers",
    "custom_providers",
    "credential_pool_strategies",
    "model_catalog",
]


def mask(v):
    """Mask a secret-looking string for safe display."""
    if isinstance(v, str) and any(t in v.lower() for t in ("key", "secret", "token")):
        return f"len={len(v)} prefix={v[:6]!r}"
    return repr(v)


def merge_block(src_val, dst_val):
    """Merge a single block. For `model`, dst wins for keys src lacks.
    For everything else, src is authoritative (replaces dst)."""
    if not isinstance(src_val, dict) or not isinstance(dst_val, dict):
        return src_val
    merged = dict(src_val)
    for k, v in dst_val.items():
        merged.setdefault(k, v)
    return merged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC, help="source config.yaml (main profile)")
    ap.add_argument("--dst", default=DEFAULT_DST, help="target config.yaml (lite profile)")
    ap.add_argument(
        "--blocks",
        default=",".join(DEFAULT_BLOCKS),
        help="comma-separated top-level keys to overlay",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would change without writing",
    )
    args = ap.parse_args()

    blocks = [b.strip() for b in args.blocks.split(",") if b.strip()]

    # Lazy import so --help works without PyYAML
    try:
        import yaml
    except ImportError:
        print("FATAL: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
        sys.exit(1)

    for p in (args.src, args.dst):
        if not os.path.exists(p):
            print(f"FATAL: missing {p}", file=sys.stderr)
            sys.exit(1)

    with open(args.src) as f:
        src_cfg = yaml.safe_load(f) or {}
    with open(args.dst) as f:
        dst_cfg = yaml.safe_load(f) or {}

    changes = []
    for k in blocks:
        src_val = src_cfg.get(k)
        if src_val is None:
            continue
        old_dst = dst_cfg.get(k)
        if k == "model":
            new = merge_block(src_val, old_dst or {})
        else:
            new = src_val
        if old_dst != new:
            dst_cfg[k] = new
            changes.append(k)

    if not changes:
        print(f"[no-op] {args.dst} already has all requested blocks up to date")
        return

    print(f"[changes] {', '.join(changes)}")
    print(f"[source ] {args.src}")
    print(f"[target ] {args.dst}")

    if args.dry_run:
        print("[dry-run] would write:", args.dst)
        return

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    bak = f"{args.dst}.bak-pre-merge-{ts}"
    shutil.copy2(args.dst, bak)
    print(f"[backup ] {bak}")

    with open(args.dst, "w") as f:
        yaml.safe_dump(dst_cfg, f, sort_keys=False, default_flow_style=False, allow_unicode=True)
    os.chmod(args.dst, 0o600)
    print(f"[wrote  ] {args.dst} (mode 0600)")

    # Validate
    with open(args.dst) as f:
        reloaded = yaml.safe_load(f)
    print("\n[model block now in target]")
    m = reloaded.get("model", {})
    for k, v in m.items():
        print(f"  {k}: {mask(v)}")
    if "custom_providers" in reloaded:
        cps = reloaded["custom_providers"]
        if isinstance(cps, list):
            print(f"\n[custom_providers] count: {len(cps)}")
            for p in cps:
                if isinstance(p, dict):
                    n = p.get("name") or p.get("label") or p.get("id") or "?"
                    b = p.get("base_url") or p.get("baseUrl") or p.get("url") or "?"
                    print(f"  - {n}: {b}")


if __name__ == "__main__":
    main()
