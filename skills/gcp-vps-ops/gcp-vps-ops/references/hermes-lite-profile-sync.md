# Hermes-Lite Profile Sync — `HERMES_HOME` = `.hermes-lite` trap

This reference covers the **dual-profile** layout common on a constrained
remote VPS where a slim `hermes-lite` gateway co-exists with a full
`~/.hermes/` Hermes on the local box. It complements the bundled-feishu
deployment story in `hermes-feishu-gateway-deployment.md`.

## Architecture: two `HERMES_HOME` values

| Profile | Home | Install | Role |
|---|---|---|---|
| Full Hermes | `~/.hermes/` | local, rich config | user's main environment, 80+ config keys, dozens of skills |
| Hermes-Lite | `~/.hermes-lite/` | remote VPS, slim | Lark-channel-only gateway on a 1v1g e2-micro |

`HERMES_HOME` is the env var Hermes uses to resolve all per-user state:
`config.yaml`, `auth.json`, `memories/`, `skills/`, `sessions/`,
`logs/`, `state.db`, `cache/`. **The systemd unit's `Environment=HERMES_HOME=...`
line is the source of truth** — without it, Hermes defaults to
`~/.hermes/`.

## The trap: gateway loses its config on restart

A 2026-06-22 incident on `instance-20260413-080555`:

1. User added `Environment=HERMES_HOME=/home/caozuohua99/.hermes-lite`
   to the systemd unit at 01:45–01:49 (intent: isolate lite's state dir).
2. systemd only re-reads the unit on next service start. The running
   process kept the old (no `HERMES_HOME`) behaviour, so the bot kept
   working **for 6+ hours** with the user's full config from
   `~/.hermes/`.
3. At 04:39 a memory-pressure OOM + curator shutdown triggered
   `Restart=on-failure`. The new process at 04:51 inherited the unit's
   new `HERMES_HOME` value.
4. From that point, **all reads came from `~/.hermes-lite/`** — and
   that directory only had a 951-byte minimal `config.yaml` with
   `model: {context_length, max_tokens}` and no provider block.
5. First inbound DM 6 hours later got `Primary provider auth failed:
   No inference provider configured` and a 199-char canned fallback.
   `/model` `/status` `/help` returned 305/200/6214-char default stubs
   because the bot had no `MEMORY.md` and no user-local skills loaded.

**Symptom signature**: gateway active, Lark WS connected, DM received
and replied, but reply is canned (`api_calls=0`) and the bot has no
agent context. Most common cause: `HERMES_HOME` on the unit points at
a directory that lacks the user's config.

## Diagnosis recipe

```bash
# 1. Which HOME is the unit pointing at?
gcloud compute ssh INSTANCE --zone=ZONE --command='systemctl show hermes-lite -p Environment,EnvironmentFiles,WorkingDirectory'

# 2. Compare top-level keys of both configs
gcloud compute ssh INSTANCE --zone=ZONE --command='python3 -c "
import yaml
m = yaml.safe_load(open(\"/home/caozuohua99/.hermes/config.yaml\"))
l = yaml.safe_load(open(\"/home/caozuohua99/.hermes-lite/config.yaml\"))
print(f\"main: {len(m)} keys, lite: {len(l)} keys\")
print(f\"main has, lite missing: {set(m) - set(l)}\")"'

# 3. Does the lite HOME have the user's memories/skills?
gcloud compute ssh INSTANCE --zone=ZONE --command='ls -la /home/caozuohua99/.hermes-lite/memories/ /home/caozuohua99/.hermes-lite/skills/'

# 4. Check what the bot is actually reading at LLM call time
gcloud compute ssh INSTANCE --zone=ZONE --command='tail -30 /home/caozuohua99/.hermes-lite/logs/gateway.log | grep -E "Primary provider|model|auth"'
```

If lite `config.yaml` has no `model.default` / `model.provider` /
`model.api_key`, and main does, the trap is the cause. Same for
`memories/MEMORY.md` and the 3 user-local skills in `~/.hermes/skills/`
(qpc, web_search, dev-environment).

## Fix recipe: mirror user-customized bits to `HERMES_HOME`

Three things need to land in `HERMES_HOME=`:

1. **`config.yaml` model/provider blocks** — overlay only the keys
   that main has but lite is missing/empty. Skip:
   - Platform-specific blocks (discord, telegram, slack, whatsapp,
     mattermost, matrix) — lite uses feishu only.
   - Already-merged blocks (model, providers, custom_providers,
     fallback_providers, model_catalog, credential_pool_strategies).
   - Lite-specific values (agent, browser, compression, display,
     max_concurrent_sessions, memory, onboarding, platform_toolsets,
     session_reset, skills) — lite has its own (e.g. lite's
     `agent.disabled_toolsets` deliberately disables browser/tts/etc.
     to fit 500MB MemoryMax).
2. **`memories/MEMORY.md`** — copy wholesale; lite usually missing it.
3. **`memories/USER.md`** — backup lite's stub (often a system profile
   auto-written by the running agent) before overwriting, or APPEND
   main's user profile to lite's if both have different value.
4. **User-local skills** — copy `~/.hermes/skills/{qpc,web_search,dev-environment}/`
   wholesale. Each is a small directory; preserve perms with `cp -a`
   or `shutil.copytree` and `chmod 700`.

After overlay, **restart the gateway** so the new MEMORY.md and config
take effect (Hermes caches provider state at init; runtime config
re-reads are unreliable).

## The `bin/hermes-planned-stop` Exec format error (Ubuntu 24.04)

A separate-but-related incident from 2026-06-22: the systemd unit's
`ExecStop=/home/.../bin/hermes-planned-stop` failed every shutdown with
`Failed to execute ... Exec format error`. The script itself was
correct: 19 lines of Python, LF line endings, executable bit, valid
shebang `#!/home/.../venv/bin/python`.

**Root cause**: the shebang interpreter path
`/home/.../venv/bin/python` is a symlink to `python3` which is a
symlink to `/usr/bin/python3`. **Ubuntu 24.04 ships only the versioned
`/usr/bin/python3.13` — the unversioned `/usr/bin/python3` symlink is
not present by default.** When systemd's `execve()` follows the
shebang chain, the final lookup returns `ENOEXEC` (kernel can't exec
a broken symlink chain) and surfaces as "Exec format error".

**Distinguishing diagnostic**: `gateway run` (ExecStart) uses the
absolute venv python path directly, not the shebang, so the gateway
itself starts fine. Only the shebang-driven ExecStop script fails.
The error appears at every `systemctl stop`/`restart`.

**Fix options** (any one):
- Remove the `ExecStop=` line from the unit. Hermes main has its own
  SIGTERM handler (`Received SIGTERM as a planned gateway stop — exiting
  cleanly`) that does the full drain/disconnect/save. The script was
  just a marker-file writer — losing it is harmless.
- Fix the script's shebang to `#!/usr/bin/python3.13` (or the venv's
  absolute path: `#!/home/.../venv/bin/python3.13`).
- Fix the unversioned symlink: `sudo ln -s /usr/bin/python3.13 /usr/bin/python3`.

The "remove ExecStop=" option is preferred when the script is
purely a marker writer (check its body for `write_planned_stop_marker`
or similar — if it just writes a file and exits 0, it's not load-bearing).

## Cleanup recipe: trash-before-delete

For any `hermes-lite` cleanup session, the safe pattern is **move to
`.trash-<ts>/` instead of `rm`**. Easy rollback if a restart reveals
something was load-bearing.

```bash
# 1. Identify candidates (skip source / runtime / cache)
gcloud compute ssh INSTANCE --zone=ZONE --command='find /home/caozuohua99/.hermes-lite -maxdepth 2 -type f -not -path "*/venv/*" -not -path "*/node/*" -not -path "*/hermes-agent/*"'

# 2. Move (NOT rm) candidates to trash
gcloud compute ssh INSTANCE --zone=ZONE --command='mkdir -p /home/caozuohua99/.hermes-lite/.trash-$(date -u +%Y%m%d-%H%M%S) && mv <candidate> <trash>/'

# 3. Cross-permission moves (root-owned → caozuohua99 trash) need sudo
gcloud compute ssh INSTANCE --zone=ZONE --command='sudo mv /home/caozuohua99/.hermes-lite/bin/<file> /home/caozuohua99/.hermes-lite/.trash-<ts>/<path>/'

# 4. Restart and verify no regressions
gcloud compute ssh INSTANCE --zone=ZONE --command='sudo systemctl restart hermes-lite && sleep 15 && systemctl show hermes-lite -p ActiveState,NRestarts && journalctl -u hermes-lite --no-pager --since "20 seconds ago" -p err -p warning'

# 5. After 24h of clean operation, drop the trash
gcloud compute ssh INSTANCE --zone=ZONE --command='rm -rf /home/caozuohua99/.hermes-lite/.trash-<ts>/'
```

**Typical cleanup candidates in `.hermes-lite/`** (verified 2026-06-22):
- Empty skill dirs (no `SKILL.md`): `apple/`, `communication/`
- Legacy standalone lark adapter files from before bundled-feishu
  migration: `lark_adapter.py`, `lark.log`, `lark_credentials.json`
  (the same `FEISHU_APP_ID`/`APP_SECRET` live in `.env.lark`)
- Stale sentinels: `.tirith-install-failed` (24B)
- Stale backups: `backups/AGENTS.md.hermes-upstream-backup-*`,
  `config.yaml.bak-pre-merge-*`, `config.yaml.bak-pre-sync-*`
- Old lock files: `auth.lock` (0B, 2+ days old)
- Orphan scripts no longer referenced by the unit: e.g.
  `bin/hermes-planned-stop` after removing the broken `ExecStop=`

**What to NEVER delete** (regenerates on startup or is load-bearing):
- `hermes-agent/`, `venv/`, `node/` (source + runtime)
- `state.db*`, `kanban.db*`, `sessions/`, `cache/`,
  `models_dev_cache.json` (runtime, regenerated)
- `logs/` (active logs)
- `.env`, `.env.lark` (live config)
- `memories/MEMORY.md.lock`, `*.lock` (lock files, may be re-created)
- `.update_check`, `.install_method` (state tracked by Hermes)

## Related pitfalls in this skill's main SKILL.md

- "Hermes Lite / Hermes Agent systemd unit install" — covers the
  `hermes gateway install --system` flow.
- "`.env` JSON values need single-quote wrapping" — relevant when
  building the new lite `.env` stub.
- "gcloud compute ssh session hangs when running long-lived daemons"
  — relevant when starting the gateway in foreground for tests.
- "Terminal tool BLOCKS shell-level background wrappers" — use
  `terminal(background=true)` not `setsid`/`nohup` for ad-hoc
  gateway tests.
