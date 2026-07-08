# HermesLite VPS Migration Checklist

## Before Migration

- [ ] Confirm source VPS has a recent baseline backup.
- [ ] Confirm backup SHA256 matches on the local machine.
- [ ] Export or document DNS records and Cloudflare settings.
- [ ] Record the current public IP and expected hostnames.
- [ ] Record open cloud firewall ports.
- [ ] Confirm SSH key login works and password login is disabled.

## Files To Restore From Private Backup

- [ ] `~/.hermes-lite/config.yaml`
- [ ] `~/.hermes-lite/.env`
- [ ] `~/.hermes-lite/.env.lark`
- [ ] `~/.hermes-lite/workspace/state.db`
- [ ] `~/.hermes-lite/skills/`
- [ ] `/root/new-api/.env`
- [ ] `/root/new-api/data/`
- [ ] `/etc/x-ui/x-ui.db`

## Files To Recreate From This Repo

- [ ] `/etc/systemd/system/hermes-lite.service`
- [ ] `/etc/systemd/system/hermes-lite-maintenance.service`
- [ ] `/etc/systemd/system/hermes-lite-maintenance.timer`
- [ ] `/etc/systemd/system/new-api.service`
- [ ] nginx site or stream configuration
- [ ] verification scripts under `/usr/local/sbin` or the user's bin dir

## Security Checks

- [ ] `passwordauthentication no`
- [ ] `pubkeyauthentication yes`
- [ ] new-api listens on `127.0.0.1:3000`, not `0.0.0.0:3000`
- [ ] x-ui root path returns `404`
- [ ] x-ui `webBasePath` is non-root and starts with `/`
- [ ] direct public access to `3000`, `50404`, and `44301` is blocked
- [ ] new-api registration is disabled
- [ ] only expected users exist in new-api
- [ ] HermesLite secret redaction is enabled

## Final Acceptance

- [ ] `systemctl status hermes-lite` is active.
- [ ] `journalctl -u hermes-lite -p warning -p err` has no new blocker.
- [ ] Feishu/Lark websocket connects.
- [ ] `/status` or equivalent gateway command responds.
- [ ] A normal model request completes.
- [ ] `scripts/backup-hermes-lite.sh` creates a new archive and hash.
