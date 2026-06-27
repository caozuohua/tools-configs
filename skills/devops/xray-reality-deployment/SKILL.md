---
name: xray-reality-deployment
description: Set up, upgrade, and troubleshoot VLESS + XTLS-Vision + Reality proxy on a VPS via x-ui (3x-ui) panel. Covers the in-bound SQLite edit workflow, key generation, xray config regeneration, Shadowrocket/v2rayN share link format, and the nginx SNI conflict that blocks port 443. Use when the user mentions VLESS, Reality, x-ui version update, "更新版本", "升级 xray", or wants xray on port 443 for GFW evasion.
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [xray, x-ui, reality, vless, vps, gfw, proxy, nginx, sqlite, networking]
    related_skills: [gcp-vps-ops, lark-open-api-scopes, llm-agent-execution-patterns]
  references:
    - references/reality-flow-name-gotcha.md
    - references/nginx-sni-stream-443.md
    - references/vless-sharelink-formats.md
    - references/x-ui-inbound-sqlite-editing.md
    - references/closing-public-ports-post-plan-b.md
---

# xray Reality Deployment on x-ui

## Overview

VLESS + XTLS-Vision + Reality is the current best practice for
GFW-resistant proxy on a self-hosted VPS. **Reality** is a TLS-mimicry
protocol — your server pretends to be a real TLS endpoint
(e.g. `www.microsoft.com:443`) to a GFW probe, while actually
terminating a real VLESS+vision session with a keypair only your
client knows.

**x-ui** (3x-ui) is the standard web panel for managing xray. It
stores inbounds in a SQLite DB at `/etc/x-ui/x-ui.db` and
regenerates `/usr/local/x-ui/bin/config.json` on `systemctl restart x-ui`.

**Why this skill exists**: there are 4 specific decisions / gotchas
that bite every first-time Reality deployer:

1. **The flow name** is `xtls-rprx-vision` (NOT `xtls-rx-vision`).
   The latter is a typo that confuses with the older/renamed XTLS
   protocol. Verify with `strings` on the binary if you doubt.
2. **x-ui's "update version" feature downloads a new xray binary**
   that removes support for `xtls-rprx-direct` (the pre-vision
   flow). The error on startup is `VLESS users: "flow" doesn't support
   "xtls-rprx-direct" in this version` — fix by editing the DB
   to use `xtls-rprx-vision`.
3. **The SQLite DB at `/etc/x-ui/x-ui.db` is the source of truth.**
   `config.json` is regenerated from it on restart. Direct edits
   to `config.json` get overwritten — you must edit the DB.
4. **Reality wants port 443** to look like normal HTTPS, but
   nginx already has it (for HTTPS panel/API). See
   `references/nginx-sni-stream-443.md` for the SNI-routing fix.

## When to use

Triggers — any of these:

- User says "升级 xray", "更新版本", "升级 x-ui", "VLESS 改 Reality"
- User wants GFW-resistant proxy setup
- User sees `VLESS users: "flow" doesn't support "xtls-rprx-direct" in this version` error
- User wants xray on port 443 (to look like HTTPS to GFW)
- User wants a `vless://...` share link for Shadowrocket / v2rayN / Clash
- x-ui panel is up but xray process is dead
- New VPS needs Reality proxy from scratch

## Required inputs

Before starting, collect from the user:

| Question | Default if not answered | Why |
|----------|------------------------|-----|
| App ID + App Secret for x-ui | (required, from x-ui panel) | panel login |
| Reality "dest" (which site to mimic) | `www.microsoft.com:443` | TLS handshake target |
| Port for xray | **19591** (off-standard) or **443** (GFW-best) | see nginx conflict |
| ShortId (8 hex chars) | random — generate it | additional auth |
| Client type | Shadowrocket / v2rayN / Clash | share-link format |

## Decision: which port to put xray on

| Choice | Pros | Cons |
|--------|-----|------|
| **19591** (or any non-443) | Zero conflict, simple | GFW more likely to block; xray prints `REALITY: Listening on non-443 ports may get your IP blocked by the GFW` |
| **443** (recommended) | Looks like normal HTTPS, hardest to block | Conflicts with nginx if you also serve HTTPS for other subdomains |

**For "443" case**: implement nginx stream{} with SNI-based routing.
`/var/lib/nanobot/workspace/...` doesn't matter for this skill —
see `references/nginx-sni-stream-443.md` for the full nginx config.

**Recommendation**: start on 19591 for a quick test (1 minute to deploy),
then migrate to 443 once you've confirmed Reality works. The migration
is a 1-2 hour job but worth it for production.

## Workflow: x-ui + xray Reality (default non-443 case)

**Inputs**: App ID/Secret in hand, Reality dest chosen, port 19591.

### Step 1 — backup the x-ui DB (mandatory)

```bash
sudo cp /etc/x-ui/x-ui.db /etc/x-ui/x-ui.db.bak.$(date +%Y%m%d_%H%M%S)
sudo cp /etc/x-ui/x-ui.db /etc/x-ui/x-ui.db.pre-reality.$(date +%Y%m%d_%H%M%S)
```

x-ui does NOT version its DB. If you break it, restore from backup.

### Step 2 — generate Reality keypair and shortId

```bash
# Keypair (xray creates the keypair via its own CLI)
/usr/local/x-ui/bin/xray-linux-amd64 x25519
# Output:
#   PrivateKey: GIMaK0aI8sjbwfHBiLDhJkct7JR5F87rsM1uruM-UHo
#   Password (PublicKey): cV_GU8gCpXanrkZ8tVAsxNL903d8HK-eoz29khRD7AA

# ShortId (8 hex chars, just need any random one)
head -c 4 /dev/urandom | xxd -p
# Output: 330c620c
```

**Why 4 bytes for 8 hex chars**: each byte becomes 2 hex digits, so
`head -c 4` produces 8 hex characters. `-p` is "plain hex".

### Step 3 — find the inbound in x-ui DB and read its current state

```bash
sudo sqlite3 -header -column /etc/x-ui/x-ui.db \
  "SELECT id, port, protocol, enable, tag, remark FROM inbounds"
sudo sqlite3 /etc/x-ui/x-ui.db "SELECT json(settings), json(stream_settings) FROM inbounds WHERE id=1"
```

If the inbound shows `enable: 0` after a failed x-ray startup, that's
x-ui auto-disabling it. Set `enable=1` as part of the update below.

### Step 4 — update the inbound via Python (safer than SQL json_set)

Direct SQL `json_set()` is fragile for nested objects. Write a tiny
Python script and pipe it through SSH:

```python
# update_inbound.py
import json, sqlite3, shutil
from datetime import datetime

DB = "/etc/x-ui/x-ui.db"
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
shutil.copy(DB, f"{DB}.pre-reality.{ts}")

PRIVATE_KEY = "GIMaK0aI8sjbwfHBiLDhJkct7JR5F87rsM1uruM-UHo"
SHORT_ID    = "330c620c"
REALITY_DEST = "www.microsoft.com:443"
REALITY_SNI  = "www.microsoft.com"

conn = sqlite3.connect(DB)
cur = conn.cursor()

# Read current
cur.execute("SELECT settings, stream_settings FROM inbounds WHERE id=1")
settings_json, ss_json = cur.fetchone()
settings = json.loads(settings_json)

# Update flow
settings["clients"][0]["flow"] = "xtls-rprx-vision"  # NOTE: not xtls-rx-vision
new_settings = json.dumps(settings, ensure_ascii=False)

# Build new stream_settings
new_ss = {
    "network": "tcp",
    "security": "reality",
    "tcpSettings": {"header": {"type": "none"}},
    "realitySettings": {
        "dest": REALITY_DEST,
        "xver": 0,
        "serverNames": [REALITY_SNI],
        "privateKey": PRIVATE_KEY,
        "shortIds": [SHORT_ID]
    }
}
new_ss_json = json.dumps(new_ss, ensure_ascii=False)

cur.execute("""UPDATE inbounds
               SET enable=1, settings=?, stream_settings=?
               WHERE id=1""",
            (new_settings, new_ss_json))
conn.commit()

# Verify
cur.execute("SELECT enable, settings, stream_settings FROM inbounds WHERE id=1")
print(cur.fetchone())
conn.close()
```

Run via base64 pipeline (multi-line Python with quotes inside nested
shells is fragile without this):

```bash
# Local: write script, base64, push
python3 -c "import base64; print(base64.b64encode(open('update_inbound.py','rb').read()).decode())" > /tmp/upd.b64
cat /tmp/upd.b64 | gcloud compute ssh <instance> --zone=<zone> \
  --command='sudo tee /tmp/upd.b64 > /dev/null && sudo python3 /tmp/upd.b64 && sudo rm /tmp/upd.b64'
```

### Step 5 — restart x-ui to regenerate config.json

```bash
sudo systemctl restart x-ui
sleep 4
# Verify xray came up as child
pgrep -af xray | head -3
# Verify port 19591 is listening
ss -tlnp | grep 19591
```

### Step 6 — validate xray config (catch errors before client connects)

```bash
sudo /usr/local/x-ui/bin/xray-linux-amd64 \
  -c /usr/local/x-ui/bin/config.json -test
# Expected: "Configuration OK."
# If error: read the line, fix the JSON, retry.
```

The Reality warning `Listening on non-443 ports may get your IP blocked
by the GFW` is **expected and harmless** if you chose 19591.

### Step 7 — generate the Shadowrocket / v2rayN share link

```text
vless://<UUID>@<HOST>:<PORT>?type=tcp&security=reality\
&pbk=<PUBLIC_KEY>\
&fp=chrome&sni=<SNI>&sid=<SHORT_ID>\
&flow=xtls-rprx-vision\
#<REMARK>
```

Example with our values:

```
vless://a0f86398-40ae-4e6a-d5af-8ae4242c1a69@34.10.143.63:19591?type=tcp&security=reality&pbk=cV_GU8gCpXanrkZ8tVAsxNL903d8HK-eoz29khRD7AA&fp=chrome&sni=www.microsoft.com&sid=330c620c&flow=xtls-rprx-vision#caozuohua-xui
```

Import into Shadowrocket (iOS): copy link → open app → "+" → "从剪贴板添加".
v2rayN (Windows): same workflow, "+" → "从剪贴板导入 URL".
Clash: convert link to YAML node (manual or via converter) and add to
profile.

### Step 8 — verify on the client

Open the imported node, connect, and try to load `https://google.com`.
If the connection works → done. If `connection refused` → check
firewall, port 19591 must be open on the VPS (`sudo ufw allow 19591` or
similar).

## Verification recipe after deploy

```bash
# 1. x-ui panel still accessible
curl -sS -I https://xui.caozuohua.cloud-ip.cc -m 5 | head -3

# 2. xray process up
pgrep -af xray | head -3

# 3. xray config validates
sudo /usr/local/x-ui/bin/xray-linux-amd64 -c /usr/local/x-ui/bin/config.json -test

# 4. Inbound port listening
ss -tlnp | grep 19591
# or 443 if you went SNI-routing

# 5. No GFW-style errors in journal
sudo journalctl -u x-ui --no-pager -n 20 | grep -iE "error|fail" | tail -5
```

## Rollback procedure

x-ui DB is the source of truth. Rollback = restore the pre-edit DB:

```bash
# Find backups (timestamped)
ls -la /etc/x-ui/x-ui.db.*.bak.* /etc/x-ui/x-ui.db.pre-* 2>/dev/null

# Pick the most recent pre-reality backup
sudo cp /etc/x-ui/x-ui.db.pre-reality.<timestamp> /etc/x-ui/x-ui.db
sudo systemctl restart x-ui
```

If you also need to revert xray binary (because the new one broke the
old config), x-ui has a "version manager" in the panel that lets you
download a specific older xray. Use that to get back to a working
xray version that supports the old flow.

## Pitfalls

- **Don't use `xtls-rx-vision`** — it's a common typo. The actual flow
  name in xray 1.9+ is `xtls-rprx-vision`. Verify with
  `strings /path/to/xray | grep -E "^xtls"` to see the actual options.
- **Don't edit `/usr/local/x-ui/bin/config.json` directly** — x-ui
  regenerates it on restart from the DB. Your edits are wiped.
- **Don't trust `journalctl` for current xray state** — xray is a child
  process, and its output may or may not appear in the x-ui service's
  journal. Check `pgrep -af xray` and `/proc/<pid>/comm` instead.
- **Don't forget to set `enable=1`** — x-ui auto-disables inbounds whose
  config fails to parse. After updating, the inbound may be off.
- **The `xray -test` command is your friend** — it parses the config
  without starting the server. Use it to catch errors before restart.
- **Reality requires TLS 1.3 at the Xray layer** — your streamSettings
  must use `security: reality` (NOT `tls`). Reality does the TLS
  mimicry itself; setting `tls` too would be a conflict.
- **GFW evasion is probabilistic** — no proxy is 100% undetectable. Plan
  for rotation (different dest, different port) if the current setup
  gets blocked.

## See also

- `references/reality-flow-name-gotcha.md` — the typo trap deep-dive
- `references/x-ui-inbound-sqlite-editing.md` — the SQLite workflow in
  detail, with the schema and all editable fields
- `references/nginx-sni-stream-443.md` — putting xray on port 443 with
  nginx as front-router, including the certbot interaction
- `references/vless-sharelink-formats.md` — share link format per
  client (Shadowrocket, v2rayN, Clash, Qv2ray)
- `references/closing-public-ports-post-plan-b.md` — post-Plan-B port
  exposure audit, DOCKER-USER iptables pattern, GCP firewall
  evaluation, the loopback-test pitfall (curl + nc, same-host),
  the systemd `-` prefix for non-fatal checks, the x-ui
  no-`-listen`-flag reality, and the three-layer defense
  verification matrix. **Required reading before declaring
  Plan B complete.**
- `x-ui-and-new-api-security-posture` (sibling devops skill) — the
  next-stage hardening: x-ui `webBasePath` (not the `secret` field!)
  for hiding the panel login, new-api public-register kill switch,
  admin API body-shape traps, password max=20, and the safe order
  for revoking exposed tokens.
- `gcp-vps-ops` — base64-via-SSH file write pattern, process
  diagnostics, and other cross-cutting tools
- `lark-open-api-scopes.md` (in gcp-vps-ops) — scopes if you also need
  calendar / bitable / docs
