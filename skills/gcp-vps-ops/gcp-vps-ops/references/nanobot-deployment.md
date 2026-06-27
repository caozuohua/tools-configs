---
title: nanobot on instance-20260413-080555 — read-only diagnostic reference
source: real session 2026-06-14, gcp-vps2 user
applies_to: nanobot v0.2.1 with vps-lite profile on the user's secondary GCP VPS
---

# nanobot Deployment Reference

Companion to `gcp-vps-ops`. Captures project-specific knowledge that took
significant investigation to discover. Read this before diagnosing nanobot
issues on `instance-20260413-080555` (10.128.0.3, e2-micro, 1GiB RAM).

## Identity & paths

| Aspect | Value |
|--------|-------|
| Service user | `nanobot` (UID 995, GID 986) |
| Package version | `nanobot v0.2.1` (`/opt/nanobot/.venv/bin/nanobot --version`) |
| Source repo | `/opt/workspace/nanobot/nanobot_repo/` (separate checkout, may be caozuohua99-readable) |
| Installed venv | `/opt/nanobot/.venv/` (bin + lib/python3.13/site-packages/nanobot/) |
| Working dir | `/var/lib/nanobot/` (owner=nanobot, **permission denied for caozuohua99**) |
| Config | `/var/lib/nanobot/config.json` (default name; may not actually exist) |
| Env file | `/etc/nanobot/nanobot.env` (permission denied) |
| Workspace | `/var/lib/nanobot/workspace/` (USER.md, SOUL.md, AGENTS.md, memory/) |
| systemd unit | `/etc/systemd/system/nanobot.service` (world-readable) |
| Profile env | `NANOBOT_PROFILE=vps-lite` (set in unit, not from env file) |

`caozuohua99` is the SSH user from `gcp-vps2` and CANNOT directly read
`/opt/nanobot/nanobot/` (not even the venv's site-packages source). Use the
`systemctl show` + journal + `/proc` approach for everything.

## systemd hardening (read from unit, not guess)

```ini
[Service]
User=nanobot Group=nanobot
WorkingDirectory=/var/lib/nanobot
EnvironmentFile=-/etc/nanobot/nanobot.env
Environment=NANOBOT_PROFILE=vps-lite
ExecStart=/opt/nanobot/.venv/bin/nanobot gateway --profile vps-lite \
          --config /var/lib/nanobot/config.json
MemoryHigh=550M MemoryMax=700M TasksMax=128
ProtectSystem=strict ProtectHome=read-only
PrivateTmp=yes PrivateDevices=yes
MemoryDenyWriteExecute=yes
ReadWritePaths=/var/lib/nanobot /etc/nanobot /var/www/blog /opt/workspace
LogRateLimitIntervalSec=30s LogRateLimitBurst=1000
```

Key consequence: nanobot can ONLY write to those 4 paths. If it tries to
write elsewhere, it gets a silent EROFS (no log line) — when debugging
"why isn't this file being created?", check the path against ReadWritePaths.

## The "WebUI is cut" fact

vps-lite intentionally **disables the inbound HTTP gateway** (default port
18790). Source: `nanobot/command/builtin.py` and `runtime_profile.py`.
- `gateway.heartbeat.enabled` and similar WebUI server flags are off
- `/health` endpoint on 18790 will return closed — that is **by design**
- Inbound WebUI access requires either `full` profile or manual override

The feishu/Telegram/Discord **channels do not need 18790** — they connect
OUT to the platform's WebSocket servers. The user's bot will work fine
without 18790 ever binding.

## "lite_hidden" only filters help text

In `nanobot/command/builtin.py:714`:

```python
lite_hidden = {"/goal", "/dream", "/dream-log", "/dream-restore"}
```

This set is checked **only in `build_help_text()`** (line 717). The actual
command registration at lines 768-771 (`router.exact("/dream-log", ...)`)
is **unconditional** — the commands ARE callable in vps-lite, they just
don't show up in `/help`.

To make them discoverable without changing code: add a line to
`/var/lib/nanobot/workspace/SOUL.md` (workspace file, not the bundled
template) saying "Use `/dream-log` to view Dream activity".

To change visibility: patch `lite_hidden` in the venv file
`/opt/nanobot/.venv/lib/python3.13/site-packages/nanobot/command/builtin.py`
and `systemctl restart nanobot`. The change survives until next
`pip install --upgrade`.

## Working channels and toolset (as of v0.2.1)

From a fresh journal: `Registered 12 tools: ['apply_patch', 'cron',
'edit_file', 'exec', 'list_dir', 'managed_repo', 'message', 'pkb',
'read_file', 'web_fetch', 'web_search', 'write_file']` and
`Channels enabled: feishu`. Cron: 1 scheduled job (Dream).

Models in use: `vertex_ai/gemini-3.5-flash` (default), `gemini-3.1-flash-lite`
(token-consolidation fallback).

## Read-only diagnostic playbook (worked example)

The 2026-06-14 session diagnosed nanobot as "stuck" because port 18790
wasn't listening. That was wrong — the bot was actively processing
feishu messages. The corrected playbook:

1. **Confirm it's running**: `systemctl status nanobot.service` (no sudo)
2. **Confirm the venv exists and is intact**:
   `/opt/nanobot/.venv/bin/nanobot --version` returns `🐈 nanobot v0.2.1`
3. **Read the unit for actual config path**:
   `systemctl show nanobot.service -p ExecStart,EnvironmentFile,Environment`
4. **Check the journal for recent activity (last hour)**:
   `journalctl -u nanobot.service --since "1 hour ago" | grep -iE "processing|completed|response|error"`
5. **Check system-wide TCP for live connections**:
   `cat /proc/net/tcp` — look for `uid 995` entries, decode the hex addresses
6. **Check per-thread state** (without sudo):
   for tid in $(ls /proc/657/task/); do
     cat /proc/657/task/$tid/stat | awk '{print "state:" $3 " utime:" $14}'
   done
7. **Probe expected ports**:
   for p in 18790 8765 8900; do
     timeout 2 bash -c "echo > /dev/tcp/127.0.0.1/$p" && echo "$p OPEN"
   done

A positive signal in step 4 OR 5 (recent log line OR active TCP socket
owned by uid 995) **proves the process is working** — even if step 7
shows 18790 closed.

## The "Dream cron prunes unreferenced skills" trap

**Discovered 2026-06-16** when the user said "不要写 pkb 了" (stop using PKB)
and the next morning `skills/pkb/SKILL.md` was a 0-byte file:

```
Jun 16 05:05:37 nanobot[626]: exec({"command": "rm -rf skills/pkb"})
Jun 16 05:05:40 nanobot[626]: write_file({"path": "skills/pkb/SKILL.md", "content": ""})
```

**What happened**: The Dream cron job runs `memory consolidation` on a
schedule (default every 4h in v0.2.1, logs show 02:00 / 05:00 / 07:00 / 09:00).
It uses an LLM with read access to `USER.md`, `MEMORY.md`, and `skills/*/SKILL.md`
to decide which skills are "live" (still actively used by the user) and
which are "dead" (no longer referenced). **Dead skills get their `SKILL.md`
emptied (0 bytes), and the directory may also get removed via `rm -rf`.**

**The trap**: This is not announced to the user. The next session can
log into the remote VPS, find a missing skill, and not realize it was
auto-pruned vs. never installed. The journal will have the `exec` and
`write_file` lines if you grep for the skill name.

**How to verify a skill was Dream-pruned (vs. never existed)**:

```bash
# Check skill directory state
sudo -u nanobot ls -la /var/lib/nanobot/workspace/skills/<name>/
# 0-byte SKILL.md = Dream cleared it (it existed)
# No directory at all = either never installed or Dream also did `rm -rf`

# Check journal for prune actions
sudo journalctl -u nanobot.service --no-pager | grep -E "skills/<name>"

# Check Dream commit history (Dream is git-backed, so its writes are committed)
sudo -u nanobot git -C /var/lib/nanobot/workspace log --oneline -- skills/<name>/
```

**Operational consequences**:

1. **To "stop using X"** (per user request): you must edit USER.md / MEMORY.md
   to remove references to X. Otherwise Dream will see the references and
   keep the skill. Telling the agent "stop writing to PKB" alone is not
   enough — USER.md must be updated for Dream to act on the new policy.

2. **To restore a pruned skill**: just `write_file` a new `SKILL.md` with
   the same name. Dream won't auto-resurrect a dead skill, but the next
   run won't delete it again if USER.md doesn't reference it as "active".

3. **Dream runs are visible in journal**: search for `Dream:` and
   `cron: executing job 'dream'` lines. The 5:00 / 9:00 / 13:00 / etc.
   times are when consolidation runs. If Dream did a meaningful prune,
   you'll see `write_file` or `exec rm` lines with the affected paths.

4. **Dream's "I pruned X" message is misleading**: in this session the
   bot reported `I have successfully consolidated and pruned the user's
   long-term memory files according to the MECE classification rules...`
   — the user-facing message is generic and doesn't name the specific
   skill that got cleared. Audit the journal for the real action.

**Why this matters operationally**:

- If the user has a high-stakes skill (e.g. a custom command) that
  Dream might misclassify as "dead", monitor the journal after the
  next 5:00 cron run to confirm it survived.
- If the user wants to *disable* a skill without losing it, add it
  to `disabledSkills: []` in `config.json` (not by removing references
  from USER.md — that triggers Dream prune).
- The Dream MECE policy is in `templates/agent/dream.md` in the nanobot
  source repo. Read it once to understand what "live" vs "dead" means
  to the LLM doing the consolidation.

## LLM hallucination: the dream-log case

The bot's LLM called `exec("/usr/bin/dream-log --status")` — a phantom
binary. The actual command in v0.2.1 is the chat command `/dream-log`
(in feishu/telegram). Source of confusion:

- `templates/agent/dream.md` describes Dream policy (what to keep/delete)
  but does NOT mention a CLI binary
- `nanobot/command/builtin.py:768-769` registers `/dream-log` as a
  chat command, not as a shell tool
- The model's prior knowledge of CLI conventions led it to construct
  `/usr/bin/dream-log` as a plausible-looking path

**Verification recipe when the bot calls a phantom CLI**:

```bash
# 1. Check if the binary actually exists
stat /usr/bin/<name>          # ENOENT = hallucinated
which <name>                  # empty if not in PATH
find / -name "<name>"         # scope to /opt /var /home /etc to avoid timeout

# 2. Check if the action is a chat command in source
grep -rn "<name>\|<name>-log" /opt/workspace/nanobot/nanobot_repo/nanobot/command/
# If hits router.exact/prefix lines: it's a chat command, not a binary
```

If the action is a chat command: tell the user to type `/<name>` directly
in feishu, or add a SOUL.md hint so the model suggests it next time
instead of inventing a shell path.

## Quick re-investigation commands (copy-paste)

```bash
# Identity
gcloud compute ssh instance-20260413-080555 --zone=us-central1-c \
  --command='hostname; uptime; free -h; df -h / | head -2'

# Service health
gcloud compute ssh instance-20260413-080555 --zone=us-central1-c \
  --command='systemctl is-active nanobot.service; systemctl status nanobot.service --no-pager | head -15'

# Recent activity (look for processing/completed lines)
gcloud compute ssh instance-20260413-080555 --zone=us-central1-c \
  --command='journalctl -u nanobot.service --since "30 min ago" --no-pager | grep -iE "processing|completed|response|error|warn" | tail -20'

# Live connections owned by nanobot (uid 995)
gcloud compute ssh instance-20260413-080555 --zone=us-central1-c \
  --command='awk "\$4==\"01\" && \$10==995 {print \$2, \"->\", \$3}" /proc/net/tcp'

# Process tree
gcloud compute ssh instance-20260413-080555 --zone=us-central1-c \
  --command='ls /proc/$(systemctl show -p MainPID --value nanobot.service)/task/ 2>/dev/null'
```

## When to escalate to sudo

These genuinely require `sudo` and are worth requesting user approval:

- `sudo cat /var/lib/nanobot/config.json` — actual runtime config
- `sudo cat /etc/nanobot/nanobot.env` — secrets, model config
- `sudo ls /opt/nanobot/.venv/lib/python3.13/site-packages/nanobot/`
  — the installed source (most cases can be avoided by reading
  `/opt/workspace/nanobot/nanobot_repo/` instead)
- `sudo ls -l /proc/<pid>/fd/` — full socket inventory
- `sudo ss -tnp` — per-socket process attribution

Always try the non-sudo equivalent first. The user's preferred
escalation is to ask in the chat and let them respond — do NOT batch
sudo commands and hope the approval sticks.
