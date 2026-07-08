# HermesLite VPS Baseline

This directory is the public, non-secret baseline for rebuilding a small VPS
that runs HermesLite, new-api, x-ui/xray, and nginx.

It intentionally contains templates and repeatable checks only. Real secrets,
SQLite databases, certificates, and full backup archives must stay outside this
public repository.

## What Belongs Here

- systemd unit templates
- nginx routing templates
- `.env.example` files with placeholder values
- HermesLite `config.yaml.example`
- verification scripts
- backup and restore scripts that operate on local VPS paths
- migration checklists and operational notes

## What Must Stay Out Of Git

- `~/.hermes-lite/.env`
- `~/.hermes-lite/.env.lark`
- `~/.hermes-lite/workspace/state.db`
- `/etc/x-ui/x-ui.db`
- `/root/new-api/data/`
- TLS private keys
- API keys, Feishu/Lark tokens, OpenRouter keys, new-api root passwords
- `hermes-lite-baseline-*.tar.gz`

## Current Production Shape

- HermesLite runs as `hermes-lite.service`.
- HermesLite home is `/home/caozuohua99/.hermes-lite`.
- new-api is bound to `127.0.0.1:3000`.
- x-ui panel is bound to port `50404`, but direct public access should be
  blocked by firewall and hidden behind a non-root `webBasePath`.
- nginx is the public entry point for `80/443`.
- Direct public access to `3000`, `50404`, and xray internal ports should be
  denied at the cloud firewall layer.

## New VPS Flow

1. Provision the host and create the runtime user.
2. Install system packages: nginx, sqlite3, docker, certbot if needed.
3. Install HermesLite under `/home/<user>/.hermes-lite`.
4. Copy real secrets from the encrypted/private backup, not from this repo.
5. Install systemd units from `systemd/*.example`.
6. Install nginx config from `nginx/`, then test with `nginx -t`.
7. Restore runtime state from a private backup archive.
8. Run `scripts/verify-hermes-lite.sh`.
9. Run `scripts/verify-public-ports.sh <public-ip>`.
10. Send a real Feishu/Lark test message and check `gateway.log`.

## Local Backup Convention

Keep private backup archives on the operator machine, for example:

```text
D:\Geek\hermes-lite-backups\
```

The archive can contain secrets because it is not committed. Verify each copy
with the adjacent `.sha256` file before treating it as restorable.
