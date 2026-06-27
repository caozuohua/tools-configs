---
name: avoid-false-positive-warnings
description: "Cross-check daemon/agent WARNING/ERROR output against actual system state before diagnosing or fixing. Avoids acting on parser bugs, stale logs, or self-check false positives in journal output."
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [debugging, verification, systemd, journal, hermes]
    trigger: "When you see a WARNING/ERROR in a daemon's log and are about to diagnose, report, or fix the implied issue"
---

# Avoid False Positive Warnings

## When to use

Any time you encounter a WARNING or ERROR in a daemon's log (systemd journal, application logs, structured logs) and are about to:

- Report it as a real issue
- Suggest a fix
- Run a repair command

**STOP. The warning may be a false positive.** Self-check code can have parser bugs, the log may be stale, or the daemon's view of state may diverge from actual system state.

## 4-step verification process

### Step 1: Identify the source

What code emitted the warning? Is it:

- **The daemon's own self-check** (e.g. hermes reading its own unit file) — most likely to be wrong
- **A third-party library** (e.g. lark_oapi checking config) — possible parser issues
- **The kernel** — usually authoritative
- **systemd** — usually authoritative, but `systemctl show` has known quirks (see Step 3)

### Step 2: Cross-check with the actual source of truth

Use **read-only, sudo-free** commands wherever possible:

- `grep <field> /etc/systemd/system/<unit>.service` — direct file read (world-readable)
- `cat /etc/systemd/system/<unit>.service` — full unit
- `stat -c "%y  %n" /etc/systemd/system/<unit>.service` — mtime (compare to warning timestamp)
- `systemctl show <unit> -p <field>` — but know its limits (see Step 3)
- `/proc/<pid>/status`, `/proc/<pid>/stat` — actual process state (world-readable)
- `journalctl -u <unit> --since "<warning_time>"` — historical log context

**Key test**: if file mtime is BEFORE the warning timestamp, the file content at warning time is known — use that as ground truth.

### Step 3: Check well-known parser-bug patterns

Common false-positive patterns to recognize:

- **`systemctl show -p TimeoutStopSec` returns empty** — use `-p TimeoutStopUSec` instead. Many daemons get this wrong.
- **Daemon reads its own config and compares to env** — env may have changed since startup
- **Daemon cached state at startup** — state may have changed since
- **Daemon reads file via API that returns empty for unset fields** — daemon defaults to 0 or wrong value
- **Suggested fix command in warning message doesn't exist** — warnings are written at code-write time, command names may have changed

### Step 4: Only then act

If verification confirms the issue: report "需修" with **verified evidence** (file content + mtime + cross-check).

If verification refutes: report "warning is false positive" with the actual current state and explain the root cause (parser bug, stale read, etc.).

If verification is ambiguous: say so, don't pick a side.

## Worked example: hermes-lite TimeoutStopSec (2026-06-18, instance-20260413-080555)

**Trigger** — hermes-lite journal at 10:29:32:

> WARNING gateway.run: Stale systemd unit detected: hermes-lite.service has TimeoutStopSec=90s but drain_timeout=180s (expected >=210s). systemd may SIGKILL the gateway mid-drain. Run `hermes gateway service install --replace` to regenerate the unit, or shorten agent.restart_drain_timeout.

**Mistake** (what I did wrong): Treated warning as ground truth. Reported "需修". Offered A/B/C fix options. User picked A.

**Verification revealed**:

- `grep TimeoutStopSec /etc/systemd/system/hermes-lite.service` → `TimeoutStopSec=240s` ✓
- `stat /etc/systemd/system/hermes-lite.service` → mtime `2026-06-18 04:19:14 UTC` (BEFORE warning at 10:29:32)
- File unchanged since 04:19; warning fired at 10:29 with stale 90s value

**Root cause**: hermes self-check used `systemctl show -p TimeoutStopSec` which returns empty (per gcp-vps-ops skill pitfall). Daemon parsed empty as 90s, compared to 180s drain, declared stale.

**gcp-vps-ops skill pitfall** (verbatim):

> `systemctl show <unit> -p TimeoutStopSec` returns empty even when the unit file sets it — use `TimeoutStopUSec` instead. This matters when validating third-party daemon warnings about "stale systemd unit TimeoutStopSec=X" — the warning may be a parser bug (the actual value is correct).

**Bonus finding**: The journal's suggested fix command `hermes gateway service install --replace` was also wrong — `hermes gateway service` is not a valid subcommand. Correct: `hermes gateway install --force --system --run-as-user <user>`. Always verify suggested commands before running.

- **Use the file mtime to detect staleness** — if mtime is BEFORE warning timestamp, content-at-warning-time is known
- **Status commands may show stale or partially-loaded state, not config truth** — When config says `enabled: true`, the service restarts successfully, and the journal shows "X channel enabled", but `channels status` / `plugins list` still shows ✗ / no, the cause is often a missing dependency (e.g. `discord.py not installed`) — verified 2026-06-19 on gcp-vps2 nanobot. The config IS enabled, the plugin IS in the config, but the underlying Python library is missing so the plugin can't load. Cross-check with: (a) the journal for "X not installed" / "X channel enabled" / "X ready" log lines, (b) actual network connections via `/proc/<pid>/net/tcp` to the service's gateway, (c) the absence of an "ERROR" line about the missing module. Don't conclude "config didn't take" from a ✗ status; verify with logs and runtime. The "status command is authoritative" assumption is itself a false-positive trap.

## Verification checklist before reporting "需修"

- [ ] Read the actual file (grep, cat, stat) to confirm current value
- [ ] Compare file mtime to warning timestamp (stale file = known state at warning)
- [ ] Cross-check with /proc or runtime state if possible
- [ ] Check `gcp-vps-ops` skill for known false-positive patterns (e.g. TimeoutStopSec)
- [ ] Verify any suggested fix command actually exists (`<tool> <subcommand> --help`)
- [ ] If verification confirms, THEN report "需修" with verified evidence
- [ ] If verification refutes, report "warning is false positive" with current state

## Pitfalls

- **Don't trust journal WARNINGs as ground truth** — they reflect what the daemon's code THINKS, not necessarily reality
- **Don't act on warnings without verifying** — even if user picks option A, verify first
- **Don't bundle "issue exists" + "here's the fix" in one report** — split into "found this" + "want me to verify?" + "want me to fix?"
- **Don't propose A/B/C fix menus on a non-existent problem** — wastes the user's time and triggers premature action
- **Suggested fix commands may not exist** — the daemon's code was written at one time, the CLI may have changed since
- **Use `TimeoutStopUSec` not `TimeoutStopSec`** when scripting around systemd timeouts
- **Daemon self-checks are bug-prone** — they often read config in ways that have known issues
- **Use the file mtime to detect staleness** — if mtime is BEFORE warning timestamp, content-at-warning-time is known
- **Chat-bot "echo" responses from a test script may be stale messages from previous test runs** — see below

## Chat-bot test methodology: "echo" responses might be stale messages, not LLM behavior

When testing chat bots via REST API, a script that filters for "any bot message != my sent message ID" can pick up OLD bot messages from previous test runs in the channel history — not the response to your current test. This is a different class of false positive: not in daemon logs but in **test-script output interpretation**.

**Symptom pattern** (verified 2026-06-19 on gcp-vps2 testing nanobot Discord bot): every test message gets a 4-5s response that "looks like" an LLM echo of your input. You report "bot echoes every message." Reality: the bot only ever responded to the FIRST test message, then went silent (stuck streaming state, separate bug). The "echo responses" your script kept reporting were stale bot messages from previous test runs in the channel history, picked up by `m.id != sent_id` filter — but the channel can have any number of older bot messages that match.

### Verification recipe (must do all four)

1. **Send a UNIQUE marker** in the test message — e.g. `f"uniquetest{int(time.time())}-xyz"`. A timestamp+random string. Anything less is ambiguous.
2. **Capture your sent message's timestamp** from the REST response (the `timestamp` field Discord returns).
3. **Wait the response window** (10-30s for typical LLM calls, longer for cold start).
4. **The bot's NEW response MUST satisfy ALL**:
   - `m.author.username == 'your_bot_name'` AND `m.author.id == expected_bot_id`
   - `m.timestamp > your_sent_timestamp` (strictly newer)
   - Either contains your unique marker (echo case) OR is substantively different (LLM case)

Filter by both `m.id != sent_id` AND `m.timestamp > sent_timestamp`. The timestamp filter is the one that catches stale-history false positives.

### Don't conclude from a single curl + fetch sequence

- "Bot responded with X" requires timestamp proof, not just presence of a bot message.
- "Bot didn't respond" requires seeing the channel state AFTER your sent message with no NEW bot message newer than it — not just "no message I recognize."
- Always send a unique marker so you can distinguish echo (LLM behavior) from a stale bot message in history (test-script bug).

### Worked example: nanobot Discord bot, gcp-vps2 (2026-06-19)

**Setup**: Discord bot `nabot` joined user's guild `boys`. Tested end-to-end via REST API. Bot was alive, WS connected, journal showed `bot connected as user ...`.

**Symptom** (incorrect diagnosis): "Bot responded with literal echo of every input in 4-5s." Multiple test messages all "got responses" that were exact character-for-character copies of the input.

**Verification**: sent `uniquetest1781918724-xyz` and grepped for that marker in bot messages. No marker found. The "responses" the script kept reporting were OLD bot messages from previous tests in the channel, not responses to the new test.

**Actual behavior**: bot only responded ONCE (to the very first test message ever sent after a fresh start, with a literal echo that was itself a separate bug). After that, the bot was silent — stuck in some streaming state, no logs, no responses. The user's original complaint ("no reaction in server") was 100% correct.

**Cost**: ~30 min of confused debugging, multiple "fix the LLM echo" iterations on a non-issue. Could have been caught in 60 seconds with the timestamp filter recipe above.

**Takeaway**: a chat bot that responds to EVERY test message with an exact echo is suspicious — verify with timestamp + unique marker before reporting it as LLM behavior.
