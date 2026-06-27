---
title: xray Reality on port 443 with nginx SNI routing — the "Plan B" pattern
source: real session 2026-06-15, instance-20260413-080555
applies_to: any VPS running xray Reality + nginx with multiple TLS services on the same IP
---

# Reality VPN on port 443 with nginx SNI Routing

When you need:
- A Reality-based VPN on a GFW-blocked environment
- An x-ui panel on a custom subdomain
- A new-api (or any other HTTPS service) on a custom subdomain
- **All on the same public IP, all on port 443**

The naive solution is to put each on a different port (xray on 8443,
x-ui on 443, api on 4443). The right solution is **SNI-based routing**:
nginx on port 443 inspects the TLS ClientHello SNI without decrypting,
forwards Reality traffic to xray, and forwards HTTPS traffic to the
internal nginx http terminator.

GFW detection reality: xray itself prints
"REALITY: Listening on non-443 ports may get your IP blocked by the GFW"
on startup. This is the strongest signal that **Reality needs to be on
port 443** for any real GFW evasion.

## The architecture

```
Internet:443 (single port)
  ↓
nginx stream{} (ssl_preread, sees SNI, no decrypt)
  ├─ SNI=xui.caozuohua.cloud-ip.cc  → nginx_tls (127.0.0.1:8443)
  ├─ SNI=api.caozuohua.cloud-ip.cc  → nginx_tls (127.0.0.1:8443)
  └─ SNI=www.microsoft.com (Reality)  → xray (127.0.0.1:44301)

xray listens ONLY on 127.0.0.1:44301 (internal)
nginx http listens on 127.0.0.1:8443 (internal TLS terminator)
nginx http on 0.0.0.0:80 for certbot HTTP-01 challenge + HTTPS redirect
```

## Why nginx stream (not the naive config)

You might think: just put xray on 0.0.0.0:443 and nginx on 8443. But:

1. **GFW detects Reality faster on non-standard ports** — port 8443 is
   a tell. 443 is invisible in normal HTTPS traffic.
2. **certbot's nginx plugin** re-inserts `listen 443 ssl;` on every
   renewal, fighting your custom config. Stream block on 443 is
   immune to this.
3. **You don't have to change the public URL of any other service**
   (xui.xx, api.xx keep working unchanged).

The trade-off is that nginx needs the `stream` module, which is NOT in
the default Ubuntu nginx package. See "The stream module gotcha"
below.

## x-ui DB settings for this architecture

When xray's inbound must listen only on 127.0.0.1:44301 (not
0.0.0.0:443), the x-ui DB has TWO fields to change:

```sql
UPDATE inbounds
SET listen = '127.0.0.1',  -- not null (which means 0.0.0.0)
    port   = 44301
WHERE id = 1;
```

Use SQLite to update, then `systemctl restart x-ui`. x-ui regenerates
`/usr/local/x-ui/bin/config.json` and restarts xray.

Reality fields stay identical:

```json
{
  "clients": [{"id": "<uuid>", "flow": "xtls-rprx-vision"}],
  "decryption": "none",
  "fallbacks": []
}
```

```json
"streamSettings": {
  "network": "tcp",
  "security": "reality",
  "tcpSettings": {"header": {"type": "none"}},
  "realitySettings": {
    "dest": "www.microsoft.com:443",
    "serverNames": ["www.microsoft.com"],
    "privateKey": "<x25519-private>",
    "shortIds": ["<8 hex>"]
  }
}
```

## nginx config (the full file structure)

Three files, each with a clear role. **Do not** put `stream { }` or
`http { }` in a sites-enabled file — those directives are
**top-level only**, not allowed inside an `include`d file.

### `/etc/nginx/nginx.conf` (top-level)

```nginx
user www-data;
worker_processes auto;
pid /run/nginx.pid;
error_log /var/log/nginx/error.log;
include /etc/nginx/modules-enabled/*.conf;   # <-- loads libnginx-mod-stream
# ↑ Make sure /etc/nginx/modules-enabled/50-mod-stream.conf exists
#   (created by `apt install libnginx-mod-stream`)

events { worker_connections 768; }

# === STREAM BLOCK (must be top-level, sibling to http) ===
stream {
    map $ssl_preread_server_name $backend {
        xui.caozuohua.cloud-ip.cc   nginx_tls;
        api.caozuohua.cloud-ip.cc   nginx_tls;
        default                     xray;
    }

    upstream nginx_tls { server 127.0.0.1:8443; }
    upstream xray      { server 127.0.0.1:44301; }

    server {
        listen 443;
        ssl_preread on;          # peek SNI, do NOT terminate
        proxy_pass $backend;
        proxy_protocol off;
    }
}

http {
    # === HTTP block: TLS terminator on internal 8443 ===
    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/sites-enabled/*;
}
```

### `/etc/nginx/sites-enabled/planb.conf` (server blocks only)

```nginx
# xui panel (internal-only, behind stream routing)
server {
    server_name xui.caozuohua.cloud-ip.cc;
    location / {
        proxy_pass http://127.0.0.1:50404;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
    listen 127.0.0.1:8443 ssl;
    ssl_certificate /etc/letsencrypt/live/xui.caozuohua.cloud-ip.cc/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/xui.caozuohua.cloud-ip.cc/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
}

# new-api (internal-only, behind stream routing)
server {
    server_name api.caozuohua.cloud-ip.cc;
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_buffering off;   # critical for streaming LLM responses
    }
    listen 127.0.0.1:8443 ssl;
    ssl_certificate /etc/letsencrypt/live/xui.caozuohua.cloud-ip.cc/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/xui.caozuohua.cloud-ip.cc/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
}

# port 80 — certbot HTTP-01 + HTTPS redirect
server {
    if ($host = xui.caozuohua.cloud-ip.cc) { return 301 https://$host$request_uri; }
    listen 80;
    server_name xui.caozuohua.cloud-ip.cc;
    return 404;
}

server {
    if ($host = api.caozuohua.cloud-ip.cc) { return 301 https://$host$request_uri; }
    listen 80;
    server_name api.caozuohua.cloud-ip.cc;
    return 404;
}
```

### Apply order (matters!)

1. **Backup** everything in `/root/planb-backup-<ts>/`
2. Modify `nginx.conf` to add the `stream { }` block
3. `apt install libnginx-mod-stream` if not present
4. **Move** the existing `myhosts` symlink out of `sites-enabled/`
5. Write `planb.conf` to `sites-enabled/` (server blocks only)
6. `sudo nginx -t` — must say "test is successful"
7. `sudo systemctl reload nginx` — picks up new routing
8. Update x-ui DB (xray listen + port)
9. `sudo systemctl restart x-ui` — x-ui regenerates config.json with new xray port
10. Verify with curl on xui.xx, api.xx, and (later) Shadowrocket on port 443

The brief window where Reality on 443 is broken: between step 7
(nginx reloaded) and step 9 (x-ui restarted with new xray). xui/api keep
working through this window because nginx's HTTP terminator on
127.0.0.1:8443 is already up.

## The 3 gotchas (in order of "wasted my time")

### 1. nginx default package has NO `stream` module

The Ubuntu/Debian `nginx` package only includes `with-http_*` modules.
The `stream` module is in `libnginx-mod-stream` (and others like
`libnginx-mod-stream-geoip2`).

**Symptom**: `nginx -t` fails with
`unknown directive "stream" in /etc/nginx/sites-enabled/planb.conf:5`

**Fix**:
```bash
sudo apt install libnginx-mod-stream
ls /etc/nginx/modules-enabled/   # should show 50-mod-stream.conf
```

The default `nginx.conf` has `include /etc/nginx/modules-enabled/*.conf;`
which auto-loads it. **Do not** add a separate `load_module` line
unless your nginx.conf is non-default.

### 2. `stream` and `http` directives are top-level only

If you put `stream { }` or `http { }` inside a file that's
`include`d by a directive that runs in a non-top-level context (e.g.
`include /etc/nginx/sites-enabled/*` runs inside the `http { }`
block), nginx will error:

- `unknown directive "stream" in /etc/nginx/sites-enabled/planb.conf:5` (when stream is in sites-enabled)
- `"stream" directive is not allowed here in /etc/nginx/sites-enabled/planb.conf:5` (when stream module is loaded but it's inside http context)
- `"http" directive is not allowed here in /etc/nginx/sites-enabled/planb.conf:3` (when http is in sites-enabled)

**Fix**: `stream { }` goes in `/etc/nginx/nginx.conf` directly. Only
`server { }` blocks go in `sites-enabled/`.

### 3. `xray Reality` flow name changed across versions

Xray 1.8.x: `xtls-rprx-vision` (with "rprx")
Xray 1.9.x / newer: `xtls-rprx-vision` still works
xray 26.6.1 (this user's version): `xtls-rprx-vision`

The old `xtls-rprx-direct` is **removed** in newer versions. If
you guess wrong (e.g. `xtls-rx-vision`), xray fails to start with:

```
VLESS users: "flow" doesn't support "<your-guess>" in this version
```

**Verification recipe** when in doubt:

```bash
# 1. grep the actual xray binary for known flow names
strings /usr/local/x-ui/bin/xray-linux-amd64 | grep -oE "xtls-[a-z0-9-]+" | sort -u
# Should return: xtls-rprx-vision (and possibly others)

# 2. Test config without starting xray
/usr/local/x-ui/bin/xray-linux-amd64 -c /usr/local/x-ui/bin/config.json -test
# "Configuration OK." = good
```

Note: the warning `"REALITY: Listening on non-443 ports may get your
IP blocked by the GFW"` is printed based on xray's own inbound port
in config — it checks the inbound config, not the public-facing port.
If xray listens on 127.0.0.1:44301 (behind nginx), the warning is
misleading but harmless. The public-facing port is 443 via nginx.

## Shadowrocket link for this setup

Once running, generate the link with `port=443` (not 44301 — 44301
is internal):

```
vless://<uuid>@<server-ip>:443?type=tcp&security=reality
  &pbk=<public-key>&fp=chrome&sni=www.microsoft.com
  &sid=<short-id>&flow=xtls-rprx-vision#<remark>
```

Note: `port=443` (not 19591, not 44301). Shadowrocket connects to
public 443, nginx stream block routes by SNI to xray on 127.0.0.1:44301.

## Verifying the setup (post-deploy)

```bash
# 1. xui panel still works
curl -sS -m 3 -o /dev/null -w "xui via 443 -> HTTP %{http_code}\n" \
  https://xui.caozuohua.cloud-ip.cc/

# 2. new-api still works
curl -sS -m 3 -o /dev/null -w "api via 443 -> HTTP %{http_code}\n" \
  https://api.caozuohua.cloud-ip.cc/v1/models
# Expected: 200 (panel) or 401 (api without key)

# 3. xray is on internal port, not public
ss -tlnp | grep 44301   # should show 127.0.0.1:44301
ss -tlnp | grep 19591   # should be empty (moved away from public)

# 4. nginx stream block is in place
nginx -T 2>&1 | grep -A 2 "ssl_preread"
# Should show the stream block
```

## Backup & rollback recipe

Always make a backup before any of this. The 2026-06-15 session
captured `/root/planb-backup-<ts>/` with:

```bash
TS=$(date +%Y%m%d_%H%M%S)
mkdir -p /root/planb-backup-$TS
cp -r /etc/nginx/       /root/planb-backup-$TS/nginx/
cp -r /etc/letsencrypt/ /root/planb-backup-$TS/letsencrypt/
cp /usr/local/x-ui/bin/config.json /root/planb-backup-$TS/config.json
cp /etc/x-ui/x-ui.db               /root/planb-backup-$TS/x-ui.db
```

Rollback (in reverse order):
```bash
# Restore xray inbound to 0.0.0.0:19591
sudo python3 -c "
import sqlite3
conn = sqlite3.connect('/etc/x-ui/x-ui.db')
conn.execute(\"UPDATE inbounds SET listen='', port=19591 WHERE id=1\")
conn.commit()
"

# Restore nginx
sudo rm /etc/nginx/sites-enabled/planb.conf
sudo ln -s /etc/nginx/sites-available/myhosts /etc/nginx/sites-enabled/myhosts

# Remove stream block from nginx.conf (edit manually or sed)

# Restart
sudo systemctl restart x-ui
sudo systemctl reload nginx
```

## What about certbot?

The `nginx` plugin of certbot auto-modifies nginx config on every
renewal. With Plan B, this would re-insert `listen 443 ssl;` into
the http block, conflicting with the stream block.

**Two options**:

1. Switch to `webroot` or `standalone` authenticator so certbot
   doesn't touch nginx config. Edit
   `/etc/letsencrypt/renewal/*.conf`:
   ```
   authenticator = standalone
   installer = nginx    # this line is the problem; or remove it
   ```
   Or: `sudo certbot reconfigure --authenticator standalone`.

2. Accept the conflict and re-apply the stream block after every
   renewal (every 60-90 days). Cheap if you have a script.

The standalone authenticator needs to bind port 80 to perform the
HTTP-01 challenge. Since nginx also binds port 80, **stop nginx
before the renewal**:
```bash
sudo systemctl stop nginx
sudo certbot renew
sudo systemctl start nginx
```

Or use webroot with a specific path:
```bash
# In your port-80 server block:
location /.well-known/acme-challenge/ {
    root /var/www/certbot;
}
```
And `sudo certbot reconfigure --authenticator webroot --webroot-path /var/www/certbot`.

## Reality dest choice

The `dest` field is the server Reality pretends to be. Common choices:

| Dest | Notes |
|------|-------|
| `www.microsoft.com:443` | Most common, well-tested |
| `www.yahoo.com` | Less popular, sometimes less scrutinized |
| `dl.google.com` | Google download server, good reputation |
| `www.mozilla.org` | Firefox homepage, alternative |
| `gmail.com` / `google.com` | **Avoid** — too many people use them, gets more DPI attention |

The `serverNames` list (where Reality latches) should match the dest
domain. Reality won't accept connections with SNIs outside this list
as Reality traffic (those go to the default `xray` upstream in nginx,
or to the dest if xray is on 443 directly).

## Files and references

- x-ui config: `/etc/x-ui/x-ui.db` (SQLite)
- xray config: `/usr/local/x-ui/bin/config.json` (auto-generated by x-ui)
- nginx config: `/etc/nginx/nginx.conf` + `/etc/nginx/sites-enabled/planb.conf`
- certbot config: `/etc/letsencrypt/renewal/xui.caozuohua.cloud-ip.cc.conf`
- Reality keys: stored in x-ui DB (encrypted at rest)
- Backups: `/root/planb-backup-<ts>/`
