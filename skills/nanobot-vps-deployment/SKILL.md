---
name: nanobot-vps-deployment
description: "Deploy and operate the user's nanobot fork (caozuohua/nanobot) on a constrained VPS. Covers channel config (Discord, Feishu, etc.), optional pip dep install aligned with pyproject extras, and verification. Lean-first: avoid extra deps, code stays upstream-syncable, source of truth is the user's GitHub remote."
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [nanobot, deployment, vps, channels, discord, feishu]
    trigger: "When working with the nanobot fork (caozuohua/nanobot) on a VPS — config edits, channel enablement, pip dep install, channel troubleshooting, or upstream sync"
---

# Nanobot VPS Deployment

## Project context (user's standing rules)

nanobot on `gcp-vps2` is the user's **trimmed fork** of upstream `nanobot-ai` (by Xubin Ren et al., MIT, Discord/Telegram/Feishu chat-agent framework). Hard constraints from the user:

- **No new dependencies or resource overhead** — keep installs lean. Adding a dep that isn't already declared in upstream `pyproject.toml` is an anti-pattern.
- **Code must be pushable to GitHub** (`caozuohua/nanobot`) without modification — config changes that conflict with upstream or fork-specific hacks are an anti-pattern.
- **Pull new features from upstream** — user's fork is regularly synced from upstream `nanobot-ai` main. Local patches should be minimal and conflict-free.
- **User's GitHub remote is source of truth** when uncertain — `git -C /opt/nanobot fetch origin && git log --oneline origin/main -10 && git rev-list --left-right --count HEAD...origin/main` before any non-trivial config/code change.

Before changing `config.json`, env, or running pip: confirm fork is in sync with upstream, and any new behavior matches upstream's `nanobot/channels/<channel>.py` + `nanobot/channels/base.py`.

## Architecture (verified 2026-06-19 on gcp-vps2)

- **Code**: `/opt/nanobot/` (git repo, origin = `https://github.com/caozuohua/nanobot.git`, branch `main`)
- **Systemd unit**: `/etc/systemd/system/nanobot.service` (`User=nanobot`)
- **Config**: `/etc/nanobot/config.json` (NOT in git — deployment-specific, `nanobot:nanobot`, mode 600)
- **Env**: `/etc/nanobot/nanobot.env` (NOT in git, `nanobot:nanobot`, mode 600)
- **Workspace**: `/var/lib/nanobot/workspace/` (NOT in git, session state, `nanobot:nanobot`)
- **Venv**: `/opt/nanobot/.venv/` (`nanobot:nanobot` — **owned by service user, NOT root**; run `pip install` as nanobot)
- **Service command**: `/opt/nanobot/.venv/bin/nanobot gateway --profile vps-lite --config /etc/nanobot/config.json --workspace /var/lib/nanobot/workspace`
- **Gateway port**: 18790 (loopback HTTP API, OpenAI-compatible `/v1/chat/completions`)

The user also operates a separate **hermes-lite** instance on the remote VPS `instance-20260413-080555` — that's a different codebase, don't conflate.

## Verified Google Cloud genai integration (2026-06-20)

Confirmed end-to-end working on `gcp-vps2` against GCP Vertex AI using luck-agent's reference pattern (`/opt/luck-agent/core/model_router.py`):

- **Model that actually returns a response**: `gemini-3.1-flash-lite` with `location=global`. Other plausible names either 404 (`gemini-2.0-flash`, `gemini-1.5-flash`) or raise `TypeError: 'NoneType' object is not subscriptable` (`gemini-3.5-flash`, `gemini-2.5-flash`) with `google-genai==2.9.0`. The `-flash-lite` family is the safe choice; the `-flash` and `-pro` families have a SDK config bug at small `max_output_tokens`.
- **Credentials path** (corrected from earlier memory): `/etc/nanobot/google-service-account.json` (mode `0600 root:root`, contains `project_id` + `client_email` for `api-user@...iam.gserviceaccount.com`). **Not** `/opt/luck-agent/credentials.json` (that was a stale reference from when local + remote shared a path).
- **Required env vars** in `/etc/nanobot/nanobot.env`:
  ```
  GOOGLE_CLOUD_PROJECT=project-c1ed131b-6f02-49de-9f8
  GOOGLE_CLOUD_LOCATION=global
  GOOGLE_APPLICATION_CREDENTIALS=/etc/nanobot/google-service-account.json
  GEMINI_MODEL=gemini-3.1-flash-lite
  ```
  Note: `GOOGLE_CLOUD_LOCATION=global` is required for `gemini-3.*` models; `us-central1` is required for `gemini-2.5-*` family.
- **End-to-end smoke test** — load env, instantiate provider, call `chat()`:
  ```python
  from nanobot.providers.vertex_ai_provider import VertexAIProvider
  provider = VertexAIProvider(
      project=os.environ["GOOGLE_CLOUD_PROJECT"],
      location=os.environ["GOOGLE_CLOUD_LOCATION"],
      default_model=os.environ["GEMINI_MODEL"],
  )
  resp = await provider.chat(messages=[{"role": "user", "content": "Reply with just OK."}])
  # resp.content should contain "OK"
  ```
- **GCP services required**: `aiplatform.googleapis.com` (Vertex AI) must be enabled on the project. `cloudbilling.googleapis.com` is *not* required for actual genai calls (it's only needed for `gcloud billing projects describe`), so its absence is benign.
- **Free-tier alignment**: `gemini-3.1-flash-lite` on Vertex AI is in the free / credit-eligible tier — pairs well with GCP signup credits.

## General workflow

### When the user says "反思" or "总结失误" — the reflection protocol

When the user explicitly asks for self-reflection / lesson summary (typically after a long debugging session that didn't reach resolution), follow this protocol **before proposing next actions**:

1. **List every concrete mistake** you made in this session — each as a numbered bullet with the specific action that was wrong (not "I could have done better" handwaving). Be specific: "patch #3 introduced NameError because I used `channel_id` before it was defined".
2. **Group mistakes by pattern** (e.g., "repeated 3 times: single-point trace without exhausting all dict-access points"). Patterns > incidents.
3. **Identify which mistakes are likely to recur** (vs. one-off typos). These are the ones worth storing.
4. **Propose storage targets**:
   - **Memory** for durable facts (paths, ownership, traps that don't change) — survives across sessions
   - **Skill** for procedural workflows (when to grep, when to bisect, 2-strike rule) — survives AND auto-loads when triggered
   - **Upstream PR** for upstream bugs (e.g., the `self.config.<attr>` dict/attr mismatch in nanobot itself)
5. **Do NOT re-propose next debugging steps** in the same message — the user asked for reflection, not forward motion. Forward motion comes in the next turn after they've absorbed the lessons.
6. **Do NOT apologize or hedge** ("I should have known better..."). Just list the mistakes plainly.

After the reflection message, the user typically replies with either "yes do it" (proceed with storage) or "no, focus on X" (override). Don't preemptively create memory/skill entries before the user confirms — reflection and storage are separate steps.

### Config edits

Use `jq` + `tee` + `mv` + `chown nanobot:nanobot /etc/nanobot/config.json && chmod 600`:

```bash
sudo cp /etc/nanobot/config.json /etc/nanobot/config.json.bak.$(date +%s)
sudo jq '.channels.discord.allow_from = ["*"] | .channels.discord.group_policy = "open"' /etc/nanobot/config.json | sudo tee /tmp/nanobot_config.new > /dev/null
sudo mv /tmp/nanobot_config.new /etc/nanobot/config.json
sudo chown nanobot:nanobot /etc/nanobot/config.json
sudo chmod 600 /etc/nanobot/config.json
```

Always: backup first, set owner to `nanobot:nanobot`, mode 600. Service reads the file as user `nanobot`.

### Installing optional Python deps (lean)

Use `sudo -u nanobot` so venv ownership stays with nanobot (avoids root-owned pollution):

```bash
sudo -u nanobot /opt/nanobot/.venv/bin/pip install 'nanobot-ai[<extra>]'
```

**Always match pyproject.toml extras** — do NOT install loose packages. Examples of declared extras in `pyproject.toml`:

| extra | packages |
|---|---|
| `discord` | `discord.py>=2.5.2,<3.0.0` (+ `audioop-lts` polyfill on Python 3.13) |
| `langsmith` | `langsmith>=0.1.0` |
| `pdf` | (PDF processing libs — see pyproject) |

The `[discord]` extra only pulls `discord.py` + `audioop-lts`. Lean. Installing only declared extras keeps the install aligned with what the upstream code expects — code stays pushable to GH without surprise.

If a new dep is needed but not in pyproject.toml, the right move is to add the extra upstream first, then install.

### Restart + verify

```bash
sudo systemctl restart nanobot
sleep 3
sudo journalctl -u nanobot --since "10 seconds ago" --no-pager 2>&1 | tail -20
```

Look for these log lines (in order) as success indicators:

- `Using config: /etc/nanobot/config.json`
- `Starting nanobot gateway version X.Y.Z on port 18790`
- `Registered N tools: [...]`
- `<Channel> channel enabled`
- `✓ Channels enabled: <list>`
- `Starting <channel> channel...`
- `<channel> | Starting client via <lib>...`
- `<channel> | bot connected as user <user_id>`
- `<channel> | app commands synced: N` (Discord)

NO `ERROR` lines after the channel enablement messages. If you see `X not installed`, the optional dep wasn't installed.

## Multi-signal verification (the `channels status` is NOT ground truth)

`nanobot channels status` and `nanobot plugins list` show **config-loading state**, not runtime state. They can show ✗ / no even when the channel is fully functional (verified 2026-06-19: Discord channel ran with WS to `gateway.discord.gg`, but `channels status` showed ✗ because `discord.py` had been freshly installed and the cache wasn't refreshed).

The real runtime verification signals:

| signal | what it confirms |
|---|---|
| `journalctl` — `bot connected as user X` / `app commands synced: N` | channel actually started |
| `/proc/<pid>/net/tcp` — established connections to channel gateway IP (Discord: `162.159.x.x`, Feishu: SG-region Lark IPs) | WebSocket actually connected |
| REST API to channel's gateway (Discord: `https://discord.com/api/v10/users/@me` with `Authorization: Bot <token>`) | bot identity + scope valid |
| `nanobot channels status` | **only** reflects current process state — can lag or report wrong; treat as a hint, not ground truth |

When config says `enabled: true`, restart succeeded, journal shows "channel enabled" + no errors, but `channels status` shows ✗: assume the channel IS working and verify with REST API + WS connections.

## Common gotchas

### 1. `allow_from=[]` blocks ALL users (default)

```python
# nanobot/channels/base.py:55 (and similar per-channel configs)
allow_from: list[str] = Field(default_factory=list)
allow_channels: list[str] = Field(default_factory=list)
group_policy: Literal["mention", "open"] = "mention"
```

If a user reports "the bot doesn't respond to me", check `allow_from` first. Empty list = **no one allowed**. The bot silently rejects with `You are not allowed to use this bot.` (visible only as an ephemeral message).

Solutions:

- **Specific user**: `allow_from: ["<user_id>"]`
- **Everyone in guild**: `allow_from: ["*"]` (wildcard supported — `nanobot/channels/base.py:188`: `if "*" in allow_list: return True`)
- **Open policy** (no @mention needed): `group_policy: "open"`
- **Pairing store fallback**: even if `allow_from=[]`, a user with an entry in the pairing store can still DM the bot. See `nanobot/pairing/store.py`.

To find a Discord user ID: REST API `GET /guilds/{guild_id}/members` with the bot's token. Output includes `id`, `username`, `bot` flag, `owner` flag.

### 2. Missing optional dep silently disables channel

If `discord.py` (or `python-telegram-bot`, `slack-sdk`, `dingtalk-stream`, etc.) is missing from venv, the channel logs `<lib> not installed. Run: pip install nanobot-ai[<extra>]` and silently fails. The config says `enabled: true` but the channel won't start.

Fix: `sudo -u nanobot /opt/nanobot/.venv/bin/pip install 'nanobot-ai[<extra>]'` then restart.

### 3. `nanobot gateway service install` does NOT exist

Some legacy warnings / docs suggest `nanobot gateway service install --replace` (wrong — `service` is not a subcommand). The correct command is `nanobot gateway install --force --system --run-as-user <user>`. Always verify suggested commands via `<tool> <subcommand> --help` before running.

### 4. `systemctl show -p TimeoutStopSec` returns empty

When scripting around systemd timeouts, use `TimeoutStopUSec` (microseconds). `TimeoutStopSec` (seconds) returns empty even when set. Some upstream daemon self-checks read via `systemctl show -p TimeoutStopSec` and false-positive on stale config. See `avoid-false-positive-warnings` skill for the canonical case (hermes-lite TimeoutStopSec false-positive).

### 5. Redactor workarounds specific to nanobot work

When pushing secrets (bot tokens, app secrets) or running complex bash that touches credentials, the Hermes terminal redactor can bite. Patterns + fixes in `gcp-vps-ops/references/hermes-redactor-workarounds.md`. Key ones for nanobot work:

- `sudo -u nanobot bash -c 'grep "^KEY=*** file'` — closing `'` after `=` is eaten → use `cat` inside `sudo -u` instead, or write bash to a file via write_file
- Python `line.startswith('KEY=***')` → `':` eaten, SyntaxError → use `split('=')` + `if k == 'KEY'`
- Python `urllib.request` against Discord REST → 403 with empty body → use `subprocess.run(['curl', ...])` with token in argv

### 6. Cross-host isolation — don't pollute remote hermes-lite

When working on `gcp-vps2` (local) with SSH into `instance-20260413-080555` (remote hermes-lite), keep Hermes configuration strictly host-local:

- **Hermes-internal tools are LOCAL-ONLY**: `skill_manage`, `memory`, `write_file`, `patch`, `read_file`, `search_files`, `execute_code` — these all operate on the Hermes **current host's** filesystem (i.e., `gcp-vps2`), regardless of any active SSH session. They never touch the remote VPS's `~/.hermes/` directory.
- **SSH (gcp-vps-ops skill) is for remote service operations only**: editing `/etc/x-ui/`, `/usr/local/x-ui/`, `/opt/hermes-lite/`, restarting services, tailing logs. **Do NOT** write to `~/.hermes/skills/`, `~/.hermes/memory/`, `~/.hermes/profiles/` on the remote host — those belong to the remote hermes-lite's profile, not yours.
- **Confirmation ritual before SSH work**: `hostname; pwd; whoami` to confirm you're on the right host. After SSH: `exit`. If you find yourself about to `scp` a local skill to remote `~/.hermes/`, stop — that's a configuration leak between profiles.
- **Reflection summaries, lesson captures, skill patches, memory updates**: always local. Never sync to remote hermes-lite profile (it's a separate runtime with separate concerns — it doesn't need your nanobot/Lark/CF memories).
- **What CAN legitimately cross the SSH boundary**: data files (e.g., Bitable handoff markdown, service config backups, agent→Bitable handoff files at `/var/lib/nanobot/workspace/inbox/<topic>_<YYYY-MM-DD>.md`), NOT metadata (skill / memory / reflection).

If a future task genuinely requires syncing a skill to remote hermes-lite (rare — typically only when the user explicitly asks for the same skill on both profiles), confirm with the user first and prefer git-based distribution (push to GitHub, pull on remote) over `scp` of metadata.

## Deployment facts (verified on gcp-vps2, 2026-06-19/20)

These are concrete facts about THIS nanobot installation — if they drift, the bot stops working silently. Verify before assuming.

### `/etc/nanobot/` directory must be `chmod 0770`, not `0750`

```bash
sudo stat -c '%a %U:%G %n' /etc/nanobot/
# Expected: 770 root:nanobot (or similar owner with nanobot group write)
```

`nanobot/config/paths.py:30` has `get_data_dir() = ensure_dir(get_config_path().parent)`. The runtime data dir is the **config dir's parent**. When config lives at `/etc/nanobot/config.json`, runtime data goes to `/etc/nanobot/` (media/, cron/, logs/, webui/ subdirs). If the directory is mode `0750` (group=r-x), nanobot user (in `nanobot` group) cannot write → `PermissionError: '/etc/nanobot/media'` on every inbound message → silent drop. Fix: `sudo chmod 0770 /etc/nanobot/`. The systemd unit's `ReadWritePaths=/etc/nanobot` author already intended nanobot to write there — the underlying FS perms were just inconsistent.

### `nanobot.env` requires `GEMINI_MODEL` (not just project/location)

The Vertex AI provider needs `GEMINI_MODEL` to know which model to call. Luck-agent's `model_router.py` uses `gemini-3.1-flash-lite` with `location=global` (project-c1ed131b-6f02-49de-9f8). Other Gemini families fail on this project:
- `gemini-2.0-flash`, `gemini-2.0-flash-lite`, `gemini-1.5-flash*` → `404 NOT_FOUND` (Publisher model not found)
- `gemini-2.5-flash`, `gemini-3.5-flash` → `TypeError: 'NoneType' object is not subscriptable` (config or SDK bug with `max_output_tokens`)
- `gemini-3.1-flash-lite @ global` → ✓ works (this project's lucky combo)
- `gemini-flash-latest @ global` → ✓ works (alias fallback)

Required env vars for Vertex AI:
```bash
GOOGLE_CLOUD_PROJECT=project-c1ed131b-6f02-49de-9f8
GOOGLE_CLOUD_LOCATION=global
GOOGLE_APPLICATION_CREDENTIALS=/etc/nanobot/google-service-account.json
GEMINI_MODEL=gemini-3.1-flash-lite
NANOBOT_VERTEX_ENABLED=true
```

### Upstream `cli/commands.py:33` hardcodes `level="INFO"` — local patch in place

When nanobot starts, `cli/commands.py` removes the default loguru handler and adds a new one with `level="INFO"` hardcoded. This **overrides** `LOGURU_LEVEL` env var. To make nanobot respect `LOGURU_LEVEL=DEBUG`/`TRACE`, the line must be patched to read the env. Local patch in place (line 31-44 reads `os.environ.get("LOGURU_LEVEL")` or `NANOBOT_LOG_LEVEL`, fallback `"INFO"`). **Caveat**: rebasing this fork on upstream main will silently lose this patch — re-apply on every merge. Verification recipe: set `Environment=LOGURU_LEVEL=TRACE` in `/etc/systemd/system/nanobot.service`, `sudo systemctl daemon-reload && sudo systemctl restart nanobot`, then `journalctl -u nanobot` should show `<level>TRACE</level>` lines.

### `vertex_ai_provider.chat()` patched to sync genai + `run_in_executor`

Upstream uses `client.aio.models.generate_content(...)` (async genai path). This was unstable on the e2-micro instance and didn't match luck-agent's verified pattern. Local patch aligns with luck-agent's `model_router.py`:
```python
resp = await loop.run_in_executor(
    None,
    lambda: client.models.generate_content(  # sync, not .aio.
        model=requested_model, contents=..., config=...
    ),
)
return self._to_llm_response(resp)
```
This is what the end-to-end `provider.chat()` test verified on 2026-06-20 (returned `'OK.'` for "Reply with just OK." prompt).

## Channel-specific references

- `references/discord-setup.md` — full Discord channel workflow
- `references/stuck-message-diagnostics.md` — canonical silent-drop diagnostic log interpretation
- `references/cross-host-inbox-handoff.md` — pattern for sharing content (skills/memory/lessons) between Hermes profiles via `~/.hermes/inbox/` as data handoff; the inverse of "don't pollute remote `~/.hermes/`"
- Feishu / Lark — see `gcp-vps-ops/references/lark-open-api-scopes.md` for scopes; config schema same pattern as Discord (env vars + token/app_id)
- Telegram / Slack / etc. — same `allow_from` / `group_policy` pattern, different env keys; check `nanobot/channels/<name>.py` for exact config schema

## When bot is "connected" but doesn't respond (silent message drop)

**Symptoms** (verified 2026-06-20 on gcp-vps2, Discord channel):

- `journalctl -u nanobot` shows `bot connected as user X` + `app commands synced: N` cleanly
- You send a message from a real Discord client (or via REST API), and **the bot never replies**
- Journal shows **no ERROR lines** and **no per-message logs** after the startup
- `nanobot channels status` shows discord ✗ (expected — config state lag, not ground truth)

The bot is receiving the message in `on_message`, but one of ~5 silent drop points is returning before the message reaches the LLM. **There is NO exception log** because all drop points return cleanly with `self.logger.info("dropped: ...")` — but only **two** of them actually log a drop reason. The rest are silent.

### The silent drop points (in order, all in `nanobot/channels/discord.py`)

| # | Location | Drop condition | Logged? |
|---|---|---|---|
| 1 | `on_message` | message from bot itself | ✅ `dropped: self-message` |
| 2 | `_handle_discord_message` | `_is_system_message` | ✅ `dropped: system-message` |
| 3 | `_should_accept_inbound` | `not self.is_allowed(sender_id)` | ❌ silent |
| 4 | `_should_accept_inbound` | channel ID not in `allow_channels` (when set) | ❌ silent |
| 5 | `_should_accept_inbound` | `group_policy="mention"` and bot not @-mentioned | ❌ silent |
| 6 | `_handle_message` (base.py) | second `is_allowed` check fails (different code path) | ✅ `Access denied for sender X. Add them to allowFrom...` |
| 7 | `_handle_message` → `bus.publish_inbound` | agent loop not running, or bus stalled | ❌ silent |

### The trace-log pattern (the only reliable diagnostic)

Add **three** temporary INFO logs and restart. Look at journal to see which log fires:

```python
# /opt/nanobot/nanobot/channels/discord.py

# At on_message entry, BEFORE self-filter
async def on_message(self, message: discord.Message) -> None:
    self.logger.info(
        "on_message FIRED: author={} bot={} len={}",
        message.author.id, self._bot_user_id, len(message.content or "")
    )
    await self._handle_discord_message(message)

# In _handle_discord_message, AFTER self-filter AND AFTER channel_id defined
sender_id = str(message.author.id)
channel_id = self._channel_key(message.channel)  # ← must come BEFORE the log
self._remember_channel(message.channel)
content = message.content or ""
self.logger.info(
    "_handle_discord_message PROCEED: author={} channel={} content_len={}",
    sender_id, channel_id, len(content),
)

# In _handle_message (base.py), RIGHT BEFORE publish_inbound
self.logger.info(
    "_handle_message PUBLISH: sender={} chat={} content_len={}",
    sender_id, chat_id, len(content),
)
await self.bus.publish_inbound(msg)
```

**Critical pitfall** (caught me once): if you put the `PROCEED` log **before** `channel_id = self._channel_key(...)`, the log expression evaluates `channel_id` before it's bound → `NameError` → exception is swallowed by the `on_message` wrapper → **all messages silently disappear**. Always place trace logs AFTER the variables they reference are defined.

### Interpreting the diagnostic log

| What you see | What it means |
|---|---|
| `on_message FIRED` not appearing | Discord gateway not delivering events → check WS, intents, gateway URL |
| `on_message FIRED` + `dropped: self-message` | You're testing via REST API POST (which makes the bot send to its own channel) → **use the Discord UI to test** |
| `on_message FIRED` + `dropped: system-message` | Discord system event (member joined, etc.) → not a bug |
| `on_message FIRED` + `_handle_discord_message PROCEED` + nothing | `_should_accept_inbound` silent dropped (drop #3/4/5) → add a 4th trace log inside `_should_accept_inbound` to find which branch |
| All three logs fire | Message reached `bus.publish_inbound` → agent loop not processing → check cron, agent loop startup logs |
| `HANDLE_START` not appearing (after `_should_accept_inbound` returned True) | The `try: await _start_typing(...)` block raised silently — almost always a `self.config.<attr>` `AttributeError` because `ChannelsConfig.extra="allow"` makes config a raw dict. See "dict-attr silent AttributeError" section below. |
| Logs fire but no Discord reply | Agent returned text but outbound dispatcher failed → check `_finalize_stream` / `OutboundMessage` dispatch logs |

### journal: use system-level, not --user

`journalctl --user -u nanobot` returns "No entries" even when bot is logging to systemd journal. The unit is registered at **system** level (`/etc/systemd/system/nanobot.service`), not user. Use:

```bash
journalctl -u nanobot --since "1 minute ago" --no-pager
```

### Don't test by REST POST'ing to the bot

When you POST a message via Discord REST API as the bot itself, the bot's gateway **delivers that message back to the bot via on_message** — and the self-filter correctly drops it. So a REST API "echo" test will always show `dropped: self-message`, not a real response. **Use the Discord UI** (or a second account) to send a real message and watch the bot reply.

## Pitfalls (extended)

- **Don't trust `channels status` as ground truth** — verify with journal + `/proc/<pid>/net/tcp` + REST
- **Don't `pip install <package>` directly** — use `nanobot-ai[<extra>]` so install matches pyproject.toml and code stays upstream-syncable
- **Don't `sudo pip install`** — that creates root-owned files in nanobot's venv, breaking ownership. Always `sudo -u nanobot pip install`
- **Don't edit `/etc/nanobot/config.json` without backing up** — config has been regenerated by past upgrades; backup is the only safety net
- **Don't assume channel config defaults are permissive** — `allow_from=[]` is the default and means "no one allowed"; the bot silently rejects
- **Don't trust upstream's online docs** — for nanobot-specific behavior, read the source: `/opt/nanobot/nanobot/channels/<channel>.py` and `/opt/nanobot/nanobot/channels/base.py`. They diverge from online docs occasionally.
- **Don't skip `git fetch` before config changes** — if upstream renamed a config field, your local change may conflict; reconcile before pushing
- **Don't ignore `Failed with result 'exit-code'` lines in journal** — these signal real issues even when the new process started successfully (memory peak exceeded limit, OOM, etc.)
- **Don't `pkill` nanobot** — use `sudo systemctl restart nanobot`. pkill triggers Hermes safety approval gate.
- **Don't forget `modelPresets` section** — `Config._validate_model_preset` (in `nanobot/config/schema.py`) **hard-fails** if `agents.defaults.modelPreset` references a name not in the top-level `modelPresets` dict. Setting `modelPreset: "vertex-31-flash-lite"` without `modelPresets: { "vertex-31-flash-lite": { "model": "...", "provider": "vertexAi" } }` causes `ValidationError` at startup. Minimum required fields per preset: `model`, `provider`, `max_tokens`, `context_window_tokens`, `temperature`.
- **Don't patch source code with trace logs before variables are defined** — placing a log expression that references `channel_id` before `channel_id = self._channel_key(...)` raises `NameError`, which the async event wrapper swallows silently. All subsequent messages disappear with no error. **Always define-then-log.**
- **Don't test message delivery via REST API POST** — REST POST as the bot makes the gateway echo the message back to the same bot, where the self-filter correctly drops it. The "echo" you see is the **previous** bot reply, not a new one. Use the Discord UI or a second account.
- **Don't assume `channels.discord.allow_from` is a pydantic field** — `ChannelsConfig` uses `extra="allow"`, so `config.channels.discord` is a plain `dict`, not a model. The runtime `is_allowed()` check (`base.py:183`) reads via `self.config.get("allow_from")` — works for dicts — so your `"*"` value is honored. But pydantic-style attribute access won't work for arbitrary channel configs.

### dict-attr silent AttributeError: the class of bug that ate my afternoon (2026-06-20)

The runtime path that ACTUALLY drops messages had this line in `_should_accept_inbound`:

```python
allow_channels = self.config.allow_channels   # ← AttributeError when config is dict
```

`ChannelsConfig.extra="allow"` makes `config.channels.discord` a raw `dict`. The pydantic model field `allow_channels: list[str] = Field(default_factory=list)` on `DiscordChannel` is **never instantiated** — there's no model object to read from. So `self.config.allow_channels` raises `AttributeError: 'dict' object has no attribute 'allow_channels'`.

The same pattern repeats for `read_receipt_emoji`, `working_emoji`, `working_emoji_delay`, `streaming`, and any other field the upstream code reads via `self.config.<attr>`. Each one is a potential silent drop:

```python
# All of these raise AttributeError when config is a raw dict:
self.config.allow_channels
self.config.read_receipt_emoji
self.config.working_emoji
self.config.working_emoji_delay
self.config.streaming       # in base.py:180, has try/fallback but loses the trace
```

The bug is invisible because:
- `try/except` only wraps `add_reaction` and `is_allowed` paths.
- The `AttributeError` from `allow_channels = ...` raises **before** `_should_accept_inbound` returns.
- The async event wrapper in `discord.py` swallows the exception (logged at DEBUG level by default).
- `journalctl` shows `on_message FIRED` and `PROCEED` (those landed before the dict-attr access) but **nothing after** — looks like a downstream LLM stall, not a 1-line attr access bug.

### The dict-safe access pattern (use everywhere self.config is touched)

```python
if isinstance(self.config, dict):
    value = self.config.get("<key>") or self.config.get("<camelCase>") or <default>
else:
    value = getattr(self.config, "<key>", <default>)
```

Or as a helper:

```python
def _cfg_get(self, key: str, default=None):
    """Dict-safe config access for nanobot channel configs (ChannelsConfig.extra='allow' makes self.config a raw dict)."""
    if isinstance(self.config, dict):
        return self.config.get(key, default)
    return getattr(self.config, key, default)
```

### Diagnostic: how to spot a dict-attr AttributeError vs a real LLM stall

When journal shows `on_message FIRED` + `PROCEED` then **complete silence**, it's almost always a dict-attr AttributeError, NOT a LLM/agent stall. Add a trace log **inside** `_should_accept_inbound` and **inside** the post-accept handler (typing, reaction add, `_handle_message` call) to find the exact line. The first trace log that fires + the next one that doesn't = the line with the bug.

```python
# In _handle_discord_message, after _should_accept_inbound returns True:
self.logger.info("HANDLE_START: read_emoji={} work_emoji={}", read_emoji, work_emoji)
try:
    await self._start_typing(message.channel)
    self.logger.info("TYPING_OK")
except Exception as e:
    self.logger.warning("typing failed: {}", e)
try:
    await message.add_reaction(read_emoji)
except Exception as e:
    self.logger.warning("reaction failed: {}", e)
try:
    await self._handle_message(...)   # already wrapped, but add logger.error for visibility
    self.logger.info("_handle_message RETURNED OK")
except Exception as e:
    self.logger.error("_handle_message EXCEPTION: {}: {}", type(e).__name__, e)
    raise
```

**Critically**: the upstream code wraps only `add_reaction` in try/except — NOT `_handle_message` itself (well, it does, but the exception path is just `await self._clear_reactions(...); await self._stop_typing(...); raise`). If `_handle_message` raises BEFORE its own try/except, the AttributeError propagates up. The fix is to wrap each config-touching statement with its own try/except + log.

### The 2-Strike Rule (don't linear-hack the same pattern)

When you patch one silent-drop point, restart, ask the user to send a message, find the next silent-drop point, patch, restart, ask again — you waste the user's patience, burn turns, and accumulate stale-code confusion (the user's message may have routed to the old process). If the SAME failure pattern recurs (e.g., a second `self.config.<attr>` AttributeError after you fixed the first one):

1. **STOP patching individual sites**.
2. Grep the entire file for the pattern class: `sudo -u nanobot grep -nE 'self\.config\.\w+' /opt/nanobot/nanobot/channels/discord.py`
3. Patch ALL sites in one shot using a uniform guard:
   ```python
   if isinstance(self.config, dict):
       value = self.config.get("<key>") or self.config.get("<camelCase>") or <default>
   else:
       value = getattr(self.config, "<key>", <default>)
   ```
4. Restart ONCE.
5. Ask the user for ONE final test message — not multiple iterations.

This would have condensed the 2026-06-20 silent-drop investigation from "4 rounds of patch-restart-ask-user" into a single round. The cost of the 4-round path was substantial: ~30 minutes of user time pressing Discord buttons + 4 stale-code false positives that compounded the confusion.

**Pre-mortem before each restart**: list every `self.config.X`, `self._X.Y`, and async I/O call between your latest log line and `_handle_message`. If any could raise, wrap it in try/except + `logger.error(..., exc_info=True)` BEFORE the restart. Never restart without exhausting the static analysis of the post-trace block.

### Other pitfalls caught on the way (2026-06-20)

- **Don't write patch scripts to `/tmp` for cross-user access** — `write_file` creates files mode `0600` owned by the writer. `sudo -u nanobot python3 /tmp/your_script.py` fails with `Permission denied`. Two fixes: (a) `chmod 644 /tmp/your_script.py` after writing; (b) use `subprocess.run([...], check=True)` as the original user and only invoke `sudo` for the cross-user step. For pip installs or file edits on nanobot-owned paths, write a Python helper to `/tmp/<name>.py`, `chmod 644`, then `sudo -u nanobot python3 /tmp/<name>.py`.
- **Python `tempfile.NamedTemporaryFile('w')` rejects surrogate-pair emoji** — code containing `"\ud83d\udd04"` (🔄 as JSON-escape) raises `UnicodeEncodeError: 'utf-8' codec can't encode characters ... surrogates not allowed` on `tmp.write(src)`. Fix: replace surrogate-escape with literal ASCII placeholder (`"WRK"`) before writing the script, OR `src.encode('utf-16', 'surrogatepass').decode('utf-16')` to materialize the real codepoints before tempfile write.
- **`hermes execute_code` cannot contain nested triple-quoted strings** — the sandbox wraps your script in another layer of triple-quotes, so `r'''...'''` inside your code parses as the closing of the sandbox wrapper. Workaround: write the script via `write_file` to a `.py` file and run it via `terminal("python3 /path/to/script.py")`.

### More pitfalls from this debugging session (2026-06-20 extended)

- **Don't trust "patched source file" — Python bytecode cache may not have recompiled**. After every edit, verify the loaded bytecode actually contains your change:
  ```bash
  sudo -u nanobot strings /opt/nanobot/nanobot/channels/__pycache__/discord.cpython-313.pyc | grep '<unique_marker_from_your_patch>'
  ```
  Python skips recompile when `.pyc` embedded timestamp ≥ source `.py` mtime. If you patched via `cp` that preserved the original mtime (which `cp` does by default), the `.pyc` may be stale and the bot is still running old code. Fix: `sudo -u nanobot find /opt/nanobot -name '*.pyc' -delete && sudo systemctl restart nanobot`. **Best practice**: every patch should add a unique `INFO` log marker (e.g. `HANDLE_START_V2`) and grep for it in the pyc before claiming success.

- **`cli/commands.py:33` hardcodes `level="INFO"` — overrides `LOGURU_LEVEL` env**. nanobot's CLI does `logger.remove(); logger.add(sys.stderr, ..., level="INFO", ...)` in its module-import path. **Any env var you set** (`LOGURU_LEVEL=DEBUG`, `NANOBOT_LOG_LEVEL=TRACE`) **is ignored** by this code path — the handler-level `level="INFO"` wins. Symptom: you set `LOGURU_LEVEL=DEBUG` in systemd unit, restart, and `self.logger.debug(...)` lines still don't appear in journal. **Workaround (local patch)**: replace the hardcoded `level="INFO"` with `level=os.environ.get("LOGURU_LEVEL") or os.environ.get("NANOBOT_LOG_LEVEL") or "INFO"` so the env var is actually respected. Mark as a local modification (conflicts with upstream sync, but recoverable via search-replace). The `--verbose` / `-v` CLI flag also forces DEBUG via a separate `logger.remove(_log_handler_id); logger.add(..., level="DEBUG", ...)` block on line ~743 — use that for ad-hoc deep debugging without code patches.

- **Don't be fooled by mock `message.type = 0` triggering `_is_system_message`**. The check is `message_type not in {MessageType.default, MessageType.reply}`. `discord.MessageType` is IntEnum, and Python's `in` on a set compares by `__eq__`. An int `0` is **not** equal to `MessageType.default` (which has value 0), so `0 in {MessageType.default, MessageType.reply}` is `False`, and your mock message gets dropped as "system-message". BUT: real Discord messages pass `MessageType.default` enum instance (not int), so the actual production code path is fine. If your unit test uses `type=0` you'll false-positive on this. Don't waste a patch round chasing it.

- **Restart-timing alignment — don't ask the user to send a message before the new process is ready**. After `sudo systemctl restart nanobot`, **wait for the `bot connected as user ...` log line** before asking the user to send a test message. Discord routes inbound messages to whichever process is connected to the gateway at delivery time. If you ask before the new process finishes WS handshake, the user's message routes to the OLD process and you'll debug the wrong code path. Pattern:
  ```bash
  sudo systemctl restart nanobot
  sleep 4
  journalctl -u nanobot -n 5 --no-pager | grep -q 'bot connected' && echo READY || echo NOT_READY
  ```
  Only after READY should you tell the user "please send a message".

- **Loguru level hardcoded in `nanobot/cli/commands.py:33`** — THE trap that hides DEBUG logs. The initial `logger.add(sys.stderr, ..., level="INFO", ...)` is hardcoded. systemd unit's `Environment=LOGURU_LEVEL=DEBUG` does NOT take effect because the handler level is fixed at add-time. A `nanobot gateway --verbose` CLI flag DOES re-add a DEBUG handler (line 743), but otherwise DEBUG+ logs are silent. **Symptom**: you add `self.logger.debug(...)` traces that never appear, even though the code path runs (later INFO logs visible). **Fix** (local-only patch to cli/commands.py):
  ```python
  import os as _os
  _log_level = _os.environ.get("LOGURU_LEVEL") or _os.environ.get("NANOBOT_LOG_LEVEL") or "INFO"
  logger.add(sys.stderr, ..., level=_log_level, ...)
  ```
  After restart, `LOGURU_LEVEL=TRACE` (set in systemd unit `Environment=`) takes effect and `self.logger.debug(...)` traces actually fire. The `--verbose` flag path is preserved as backup.

- **PermissionError on `_download_attachments` after ACCEPT — fs perms vs systemd namespace mismatch**. Symptom: log shows ACCEPT then complete silence. With `logger.error(..., exc_info=True)` enabled, you see `PermissionError: [Errno 13] Permission denied: '/etc/nanobot/media'`. **Root cause**: `nanobot/config/paths.py:14` defines `def get_data_dir() -> Path: return ensure_dir(get_config_path().parent)`. On vps-lite profile, `--config /etc/nanobot/config.json` makes `config_path.parent = /etc/nanobot/`. That dir is typically `root:nanobot 0750` (group `r-x` only) — readable but NOT writable by `User=nanobot`. The systemd unit has `ReadWritePaths=/etc/nanobot ...` (intends nanobot to write there), but systemd namespace mount doesn't override file mode bits. **Fix** (minimal, 1 line): `sudo chmod 0770 /etc/nanobot/` — adds `+w` for nanobot group (which the service user belongs to). Doesn't change any file inside. **Fix** (cleaner, requires code change): patch `get_data_dir()` to return `/var/lib/nanobot/` instead of `config_path.parent`. But that's local-only and less pushable to upstream.

- **The canonical silent-drop fix: broad try/except + `exc_info=True` + no re-raise**. After exhausting all 2-Strike-Rule dict-access patches and per-call try/excepts, the final safety net is to wrap the entire `ACCEPT → _handle_message` block in **one** outer try/except that catches *anything* and logs the full traceback without re-raising. This converts the silent-discard into a visible journal ERROR, keeps the bot alive, and preserves the exception for diagnosis:
  ```python
  if not self._should_accept_inbound(message, sender_id, content):
      return
  try:
      media_paths, attachment_markers = await self._download_attachments(message.attachments)
      full_content = self._compose_inbound_content(content, attachment_markers)
      metadata = self._build_inbound_metadata(message)
      parent_channel_id = self._channel_parent_key(message.channel)
      session_key = None
      if parent_channel_id is not None:
          metadata["parent_channel_id"] = parent_channel_id
          metadata["context_chat_id"] = parent_channel_id
          metadata["thread_id"] = channel_id
          session_key = f"{self.name}:{parent_channel_id}:thread:{channel_id}"
      # ... emoji + typing + reactions + _handle_message call ...
  except Exception as e:
      self.logger.opt(exception=True).error(
          "POST_ACCEPT_EXCEPTION: {}: {}", type(e).__name__, e)
      try:
          await self._clear_reactions(channel_id)
          await self._stop_typing(channel_id)
      except Exception:
          pass
      # NOTE: do NOT re-raise — keep bot alive + leave evidence in journal
  ```
  Key technique: `logger.opt(exception=True).error(...)` (loguru) attaches the full traceback to the log entry — much more useful than `logger.error("{}", e)` which only shows the exception message. Pair with `logger.debug(...)` for normal-path breadcrumbs (each step that completes successfully), so the next bot restart + user message immediately reveals exactly which line raised.

## User explicit override — cross-host Hermes profile transfer

The `### 6. Cross-host isolation` default-DENY rule has an explicit exception path when the user **explicitly asks** to share content across profiles (e.g., "transfer local skills/memory to remote hermes-lite"). Documented workflow, verified 2026-06-20:

### When the user says "transfer" / "同步" / "share" cross-host

1. **Confirm scope + mechanism** with `clarify`:
   - What content? (all skills + memory? specific entries? lessons only?)
   - Mechanism? (git push + pull on remote, scp to inbox, instruct remote to fetch?)
   - Why? (production handover, multi-host unified knowledge, test?)

2. **Push to remote `~/.hermes/inbox/`, NOT `~/.hermes/skills/` or `~/.hermes/memory/` directly**:
   - Inbox is a data handoff zone — the receiving hermes-lite reviews INDEX and decides what to ingest.
   - Direct push to skills/memory pollutes the remote profile's runtime configuration.
   - File naming: `<topic>_<YYYY-MM-DD>.md` (matches existing inbox archive convention).

3. **Use the base64 pipeline** for SSH push (per `gcp-vps-ops` skill `pushing-secrets-via-write-file.md`):
   - Plain text via `gcloud compute ssh ... --command='cat > /path' < /tmp/file` — Hermes redactor may eat content with credentials, `(` `)` `=` `'` adjacent to credential-shaped patterns.
   - Safer: base64 encode locally → push via `tee` → decode on remote → `chmod 644`.
   - Reference script: see gcp-vps-ops SKILL.md base64 pipeline section.

4. **Always include an INDEX.md** with:
   - What's in the batch (file table with sizes)
   - Target paths on remote (if hermes-lite wants to ingest)
   - What's EXCLUDED and why (e.g., META cross-host protocol excluded — local self-discipline, not remote concern)
   - Sender identity + timestamp + sender's host (`gcp-vps2` etc.)

5. **Verify** with `gcloud compute ssh INSTANCE --zone=ZONE --command='ls -la /home/$USER/.hermes/inbox/'` — files should be owned by remote user with 644, sizes match local.

6. **META exclusion rule**: things like "cross-host isolation protocol" itself are local self-discipline and should NOT be transferred verbatim. Remote hermes-lite can adopt its own version if it wants similar protection, but it shouldn't be forced by importing the local version.

### Reference transfer batch (2026-06-20 from local gcp-vps2 → remote hermes-lite)

4 files pushed to `/home/caozuohua99/.hermes/inbox/`:
- `INDEX.md` (2.6KB) — explanation + decision rationale + recommended ingest workflow
- `memory_2026-06-20.md` (2.9KB) — 5 memory entries (excluded: META cross-host protocol)
- `skill_nanobot-vps-deployment_2026-06-20.md` (31.9KB) — full SKILL.md (410 lines, may not be directly relevant to remote but general Python-service debugging patterns are useful)
- `skills_misc_2026-06-20.md` (15.5KB) — `yuanbao` + `avoid-false-positive-warnings` (latter HIGH value for any daemon)

Remote hermes-lite then chose: copy skills to `~/.hermes/skills/`, cherry-pick memory entries into `~/.hermes/agents/default/memory/` (after creating the dir, since remote didn't have memory system yet).

## Verification checklist (use before declaring a channel "connected")

- [ ] `journalctl -u nanobot --since "10 seconds ago"` shows: `channel enabled` + `Starting client via <lib>` + `<lib> connected as user <id>` + (Discord) `app commands synced: N` — and **no ERROR lines**
- [ ] `/proc/$(pgrep -f "nanobot gateway")/net/tcp` shows established connections to channel's gateway IP
- [ ] REST API confirms identity (Discord: `GET /users/@me` returns `bot: true, verified: true`)
- [ ] (If guild) `GET /users/@me/guilds` returns expected guilds
- [ ] (Discord) `GET /applications/<bot_id>/commands` returns the synced slash commands
- [ ] (Test) Send a DM or @-mention in a channel — bot should respond (first response may take a few seconds for LLM cold start)

## Deploying prompt files to nanobot workspace

When refreshing `SOUL.md` / `AGENTS.md` / `USER.md` in `/var/lib/nanobot/workspace/` (mode 750 owned by `nanobot:nanobot`), use the base64-via-tee pattern from `references/prompt-deploy.md`. Direct `heredoc` / `cat | sudo tee` / `echo > FILE` all break on multi-line content with quotes/backticks/Chinese characters. The Python deploy script in that reference uses `sudo -u nanobot` for the actual write, and `sudo -u nanobot cat/stat` for any verification (caozuohua99 cannot read those files directly).

The same pattern + 9-test validation protocol is also documented in `references/prompt-deploy.md`.

## See also — overlapping umbrella skills

Two related skills cover complementary ground for nanobot debugging:

- **`llm-agent-execution-patterns/references/nanobot-config-gotchas.md`** — Debug-time pitfalls focused on the "bot connected but silent" pattern, with concrete 5-step debug recipe + 8 gotchas (pyc cache skip-recompile, dict-vs-pydantic attribute access, IntEnum mock false-positive, logger hardcode trap, get_data_dir() PermissionError, 2-Strike Rule, Pre-mortem, restart-timing alignment, trace log design with `exc_info=True`). **Load this when the bot is connected but doesn't respond** — it's the most direct hit-list for silent-drop debugging on vps-lite profile.
- **`llm-agent-execution-patterns/SKILL.md`** — Parent skill covers the broader "agent announces plans but doesn't execute" anti-pattern. SOUL.md / AGENTS.md patches for nanobot persona-level execution rules are in `references/nanobot-prompt-patch.md`.
- **`systematic-debugging` §5** — General async event handler silent-drop technique + Python `.pyc` cache verification (byte-level). The patterns here are framework-agnostic; `nanobot-config-gotchas.md` is the nanobot-specific application.
- **`verification-before-completion`** — Iron law: NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE. When debugging nanobot, verify at 3+ independent sources (journal + session JSONL + file mtimes) before claiming the bot is working.

The current skill (`nanobot-vps-deployment`) is broader — it covers deployment, channels, env, and operations. The `nanobot-config-gotchas.md` reference is narrower and deeper on silent-drop debugging. **Curator note**: the two have partial overlap on debug-time pitfalls; can be consolidated later, but the broader deployment coverage here justifies keeping both.
