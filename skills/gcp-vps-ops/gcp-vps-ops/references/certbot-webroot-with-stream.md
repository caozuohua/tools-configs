# Certbot webroot on a stream-routed nginx (Plan B pattern)

> Merged from `gcp-vps-certbot-webroot-with-stream` (2026-06-16 validation on `instance-20260413-080555`).

## When to use

- nginx has `stream {}` block routing port 443 by SNI (Reality + https sites)
- `certbot renew` with `authenticator = nginx` would conflict (certbot tries to write `listen 443 ssl` into http block, but stream owns 443)
- certbot dry-run hangs >90s without `--no-random-sleep-on-renew` (default flag in Ubuntu 25.10 systemd certbot.service, missing in older)

## Step-by-step

### 1. Add ACME challenge location to port 80 server block

```nginx
server {
    listen 80;
    server_name xui.example.com api.example.com;

    # ACME HTTP-01 challenge (certbot webroot mode)
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    # All other HTTP → HTTPS redirect
    location / {
        return 301 https://$host$request_uri;
    }
}
```

### 2. Switch renewal config to webroot

```bash
# Backup
sudo cp /etc/letsencrypt/renewal/<cert-name>.conf /root/backup/renewal.bak

# Edit
sudo sed -i 's/^authenticator = nginx/authenticator = webroot/' /etc/letsencrypt/renewal/<cert-name>.conf
sudo sed -i '/^installer = nginx/d' /etc/letsencrypt/renewal/<cert-name>.conf
echo "webroot_path = /var/www/html" | sudo tee -a /etc/letsencrypt/renewal/<cert-name>.conf
```

### 3. Test (always use --no-random-sleep-on-renew for speed)

```bash
sudo nginx -t
sudo systemctl reload nginx
sudo certbot renew --dry-run --no-random-sleep-on-renew
```

### 4. Verify webroot end-to-end

```bash
echo "test-token" | sudo tee /var/www/html/.well-known/acme-challenge/test
curl http://xui.example.com/.well-known/acme-challenge/test
sudo rm /var/www/html/.well-known/acme-challenge/test
```

## Pitfalls

- **Backup files in sites-enabled**: `cp` to `planb.conf.bak.*` inside `/etc/nginx/sites-enabled/` makes nginx include the backup. Always move backup to `/root/planb-backup-*/` (or other location outside sites-enabled).
- **certbot random sleep**: Without `--no-random-sleep-on-renew`, dry-run may wait 0-480s before contacting Let's Encrypt. Default Ubuntu 25.10+ certbot.service already has this flag; older systems don't.
- **gcloud compute ssh timeouts**: Long SSH commands can hit IAP tunneling timeouts. Don't `pkill -9 -f certbot` (the `-f certbot` matches gcloud's own grep too, kills SSH session). Use plain `pkill -9 certbot` or just run new certbot command — old process will exit on its own.
- **DNS resolution inside VPS**: VPS can't resolve its own custom domain (`xui.example.com` won't resolve inside the VPS). Test webroot from outside the VPS, or use `--resolve host:port:ip` with curl.
- **403 vs 200 on challenge path**: When testing with curl GET, the .well-known directory may show 403 (no autoindex). certbot creates its own file and curls that file → 200. Don't be alarmed by 403 on `curl http://host/.well-known/`.

## Files affected

- `/etc/nginx/sites-enabled/<config>` — add 80 server block with ACME location
- `/etc/letsencrypt/renewal/<cert-name>.conf` — switch to webroot authenticator
- `/var/www/html/.well-known/acme-challenge/` — auto-created by certbot

## Why nginx plugin breaks with stream{}

certbot's nginx plugin wants to add `listen 443 ssl` to its discovered server block. With stream{} owning 443, there's no `listen 443` in http{} for certbot to attach to. Result: certbot errors out or creates a broken second `listen 443` block. Webroot sidesteps this entirely — certbot only writes a single file into the webroot and doesn't touch nginx config.

## Rollback

```bash
sudo cp /root/backup/renewal.bak /etc/letsencrypt/renewal/<cert-name>.conf
# Restore original nginx config from /root/planb-backup-*/
sudo nginx -t && sudo systemctl reload nginx
```
