---
name: systematic-debugging
description: "4-phase root cause debugging: understand bugs before fixing."
version: 1.3.0
author: Hermes Agent (adapted from obra/superpowers)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [debugging, troubleshooting, problem-solving, root-cause, investigation]
    related_skills: [test-driven-development, plan, subagent-driven-development]
---

# Systematic Debugging

## Overview

Random fixes waste time and create new bugs. Quick patches mask underlying issues.

**Core principle:** ALWAYS find root cause before attempting fixes. Symptom fixes are failure.

**Violating the letter of this process is violating the spirit of debugging.**

## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If you haven't completed Phase 1, you cannot propose fixes.

## When to Use

Use for ANY technical issue:
- Test failures
- Bugs in production
- Unexpected behavior
- Performance problems
- Build failures
- Integration issues

**Use this ESPECIALLY when:**
- Under time pressure (emergencies make guessing tempting)
- "Just one quick fix" seems obvious
- You've already tried multiple fixes
- Previous fix didn't work
- You don't fully understand the issue

**Don't skip when:**
- Issue seems simple (simple bugs have root causes too)
- You're in a hurry (rushing guarantees rework)
- Someone wants it fixed NOW (systematic is faster than thrashing)

## The Four Phases

You MUST complete each phase before proceeding to the next.

---

## Phase 1: Root Cause Investigation

**BEFORE attempting ANY fix:**

### 1. Read Error Messages Carefully

- Don't skip past errors or warnings
- They often contain the exact solution
- Read stack traces completely
- Note line numbers, file paths, error codes

**Action:** Use `read_file` on the relevant source files. Use `search_files` to find the error string in the codebase.

### 2. Reproduce Consistently

- Can you trigger it reliably?
- What are the exact steps?
- Does it happen every time?
- If not reproducible → gather more data, don't guess

**Action:** Use the `terminal` tool to run the failing test or trigger the bug:

```bash
# Run specific failing test
pytest tests/test_module.py::test_name -v

# Run with verbose output
pytest tests/test_module.py -v --tb=long
```

### 3. Check Recent Changes

- What changed that could cause this?
- Git diff, recent commits
- New dependencies, config changes

**Action:**

```bash
# Recent commits
git log --oneline -10

# Uncommitted changes
git diff

# Changes in specific file
git log -p --follow src/problematic_file.py | head -100
```

### 4. Gather Evidence in Multi-Component Systems

**WHEN system has multiple components (API → service → database, CI → build → deploy):**

**BEFORE proposing fixes, add diagnostic instrumentation:**

For EACH component boundary:
- Log what data enters the component
- Log what data exits the component
- Verify environment/config propagation
- Check state at each layer

Run once to gather evidence showing WHERE it breaks.
THEN analyze evidence to identify the failing component.
THEN investigate that specific component.

### 5. Trace Data Flow

**WHEN error is deep in the call stack:**

- Where does the bad value originate?
- What called this function with the bad value?
- Keep tracing upstream until you find the source
- Fix at the source, not at the symptom

**Action:** Use `search_files` to trace references:

```python
# Find where the function is called
search_files("function_name(", path="src/", file_glob="*.py")

# Find where the variable is set
search_files("variable_name\\s*=", path="src/", file_glob="*.py")
```

### 5. Async Event Handlers That Silently Drop — Trace at Every Drop Point

**Symptom**: An event arrives (Discord message, queue task, webhook) but the handler emits no log after the entry trace. No exception, no error — the message just vanishes.

**Why it happens**: Async event handlers in Python (discord.py, asyncio tasks, aiohttp middleware) wrap the inner coroutine in framework code that **swallows exceptions** and converts them to "task completed with exception" — often logged only at DEBUG. A `return` from any inner filter (auth check, allowlist check, channel policy) is indistinguishable from a crash.

**The technique** — add an INFO trace BEFORE every potential silent return inside the handler chain. Not just at handler entry, but at every `if X: return False`:

```python
async def _handle(self, event):
    logger.info("ENTER: id={}", event.id)               # proves event arrived
    if not self._is_self(event):
        logger.info("dropped: self-message")             # ← trace 1
        return
    if not self._is_allowed(event.user_id):
        logger.info("dropped: not allowed (user={})", event.user_id)  # ← trace 2
        return
    if not self._channel_ok(event.channel):
        logger.info("dropped: channel_blocked (channel={})", event.channel.id)  # ← trace 3
        return
    logger.info("ACCEPT: proceeding to handler")         # ← only prints if all filters passed
    await self._dispatch(event)
```

**Restart, send ONE message, read the log.** The line `dropped: <X>` that matches your symptom is the bug. Two-line trace is enough; you don't need full instrumentation.

**Specific Python footgun — dict-vs-pydantic attribute access**: frameworks that load config two ways (raw dict OR pydantic model) silently break when code uses `self.config.allow_channels` (attribute) on a raw dict. The framework's `extra="allow"` policy means the section is a dict, not a model. Always guard:

```python
# WRONG — AttributeError silently swallowed by discord.py event wrapper
allow_channels = self.config.allow_channels

# RIGHT — handle both shapes
if isinstance(self.config, dict):
    allow_channels = self.config.get("allow_channels") or []
else:
    allow_channels = getattr(self.config, "allow_channels", None) or []
```

**Patch validation pitfall**: when adding trace logs **mid-function** (not at the start), verify every variable referenced in the log message exists at that line. Using `channel_id` before its `channel_id = self._channel_key(...)` line above produces a NameError that swallows the whole handler and **looks identical to a silent drop** — except it's your debug patch that caused it. Read the file fresh after every patch, restart, then re-send.

**Companion false-positive to avoid**: don't test a bot by sending messages through its own API/token. The bot's self-message filter is correct behavior, not a bug — and reading its silence as "stuck" wastes hours. Test by sending from a different user account (REST API with a different bot token, or a manual UI send).

**Trace granularity — instrument at every line of suspect code, not just function boundaries**: when you add an INFO trace `X` and the log shows entry to the function but NOT `X`, execution stopped on some line between entry and `X`. If the suspect region is 5–20 lines (a `compose → build → resolve → schedule` sequence), a single mid-function trace is too coarse — you'll be guessing which line threw. Add a trace *between each* line in the suspect region. Yes, the log gets noisy; that's the cost of locating the silent drop. Two traces in the same function is rarely enough; five to ten is normal during a debug spike.

**Verify each trace appears before adding the next (anti-pattern: piling traces)**: when an earlier trace you expected to see is missing from the journal, **stop and diagnose why** before adding deeper traces. Three checks in order:
1. Did the file actually save? `stat -c '%y %s' <file>` — mtime and size match the edit
2. Did the running process load the new code? Two cases:
   - **Compiled languages**: rebuild the artifact (`go build`, `cargo build`, `tsc`), confirm the binary mtime changed, then restart
   - **Python with `.pyc` cache**: Python invalidates `.pyc` when source mtime changes, but `cp` operations, certain editors, or NFS mounts can leave mtime unchanged. Verify by reading the loaded bytecode directly:
     ```python
     import marshal, sys
     with open('<file>.pyc', 'rb') as f:
         f.read(16)  # header (magic + timestamp + size)
         code = marshal.load(f)
     def walk(co):
         for c in co.co_consts:
             if isinstance(c, str) and 'YOUR_TRACE_STRING' in c:
                 return True
             if hasattr(c, 'co_consts'):
                 if walk(c): return True
         return False
     print('trace string in bytecode:', walk(code))
     ```
   - **Live process without restart**: any in-memory module is stale until restart. Adding code to a file the running process already imported does nothing until you restart.
3. Did the restart actually happen? `journalctl -u <svc> --since "2 minutes ago" | grep "Starting"` — confirm a new boot log line for the service. A `systemctl restart` that fails silently (unit masked, dependency loop) leaves the old process running.

Only after the previous trace is confirmed in the log should you add the next. **Piling traces** — adding three more traces because the first one didn't appear, then four more because those didn't appear, then concluding "the framework must be broken" — wastes hours. Each missing trace is a concrete signal: either the code didn't run (load issue), or it ran but didn't reach that line (exception swallowed earlier).

**Compiled-binary pitfall (symmetric to `.pyc` cache)**: Python's `.pyc` invalidation is forgiving, but Go/Rust/C/Java are not — patching a source file has zero effect until you rebuild the artifact and restart the service holding the old mmap. The "I edited the file, why didn't it change behavior" debugging hour is almost always a build/restart miss, not a logic bug. Make the rebuild + restart a single atomic step in your debug runbook.

### 6. Before Destructive Changes: Find ALL Call Sites (cross-repo)

**BEFORE deleting an API endpoint, env var, file path, CLI command, or database column:**

In any codebase that calls into the component you're changing, search for the exact string:

```bash
# Find all references — but be aware many are NOT real calls
rg -n "exact-path-or-name" /path/to/consumer-repo/

# Distinguish REAL calls from dead references:
#   - "CONSTANT_NAME = '/api/foo'"       ← string constant, often a docstring/hint
#   - fetch("/api/foo")                  ← real HTTP call
#   - _resolver("foo") → env var         ← real call, indirect via env
#   - "https://example.com/api/foo"      ← test mock, NOT a real call
```

**For HTTP endpoints specifically:**
1. `rg` the path string in the consumer's main code (`src/`, `app/`, `lib/`, NOT `tests/`)
2. Trace any indirection (env-var fallbacks, config files) to find the actual URL
3. If you find only comments, docstrings, or test mocks with `example.com`, the endpoint is orphan
4. Verify by reading the consumer's URL resolver / config loader to confirm

**Pitfall**: A reference in a `CONSTANT = "..."` definition is not a real call if the constant is never read by code that issues a request. Always check: who reads this constant? Does the read path reach an actual `fetch`/`request`/`curl`?

**For env vars:**
1. `rg` the env var name in both repos (definitions and reads)
2. If the consumer reads it but maps to a different default, the env var is functionally ignored
3. Check `.env.example` / `.env.local` for actual deployed values

**For database columns / table names:**
1. `rg` the column name in ORM models, migration files, and query code
2. `rg` in all consumer repos that connect to the DB
3. Check views, stored procs, and triggers that might reference it

**Symptom of skipping this step**: You delete something "obviously unused" and break a downstream consumer that called it through a chain you didn't trace.

### 7. Verify Single-Signal Diagnoses Before Reporting

**A single negative observation is not enough to conclude "broken" or "missing".** Before reporting a root-cause claim based on absence, gather at least one of:

- A **positive** signal of the thing working (recent log line, live network connection, recent file write, response from upstream)
- An **independent** negative signal that corroborates the first (process actually crashed vs. just not listening on the expected port)
- A **fresh verification** of any cached fact (memory says "X is disabled" — but the live system says otherwise)

**Common false-positive diagnoses this rule catches**:

- "Process is stuck" because an *expected* port isn't listening — but the service is healthy on an outbound-only channel (WebSocket client, push notifications) and the inbound HTTP gateway was intentionally cut
- "Service has no permission" because sudo failed once — but the live `sudo -l` shows broader grants than the cached policy
- "File doesn't exist" because the LLM agent claimed it does — but a `stat` confirms ENOENT (LLM hallucination, see §8)
- "Memory is stale" because the test still fails after a config change — but a `cat` of the config shows the change didn't take effect (different file, different scope)

**Diagnostic move**: when the first observation is "X is missing/closed/dead", immediately look for one of:
- `journalctl -u <svc> --since "1 hour ago" | grep -iE "processing|completed|response|error"` — was it actually idle or actually broken?
- `cat /proc/net/tcp` and `awk '$10==<uid>'` — is there a live connection proving the process is doing work?
- `systemctl show <svc> -p ExecStart,EnvironmentFile` — what config path was it actually using, vs the one you assumed?
- `sudo -l` (no sudo required to run) — what's the actual current policy?

A positive or contradictory signal costs one tool call and prevents reporting a wrong root cause.

**Bots/channels false-positive — "echo" is self-filter, not bot reply**: When debugging a Discord/Slack/Telegram bot, sending messages via REST API using the bot's own token makes the bot the message author. The framework's self-message filter (correct behavior) silently drops it. Reading the bot's lack of response as "stuck" or "echo not working" wastes hours. Verify by:
1. Sending from a different account (the human user, or a second bot token)
2. Checking the log for `dropped: self-message` — that's the *correct* behavior, not a bug
3. Only the human account's messages will be processed by the handler; bot-account messages always end at self-filter

### 8. LLM Agent Output Can Be Hallucinated Evidence

**When the system under investigation includes an LLM agent (chatbot, copilot, autonomous tool-caller), the agent's tool calls and outputs are part of the data you are debugging. The agent can invent plausible-but-nonexistent commands, paths, or facts. Do not trust an LLM-generated tool call as evidence of how the system actually works — verify against the real filesystem/source.**

**Concrete failure pattern**:
- The LLM calls `exec("/usr/bin/some-tool --flag")` to inspect subsystem state
- You, the human/agent investigating, see the tool call in the journal and assume the binary must exist
- The binary is a hallucination — it never existed; the model's prior on CLI conventions filled in a plausible path
- Investigation stalls on "why is the binary misconfigured?" when the real question is "why did the model invent a binary?"

**Verification recipe when an LLM agent called a tool that "should exist" but seems off**:

```bash
# 1. Check filesystem existence
stat /path/the/agent/used 2>&1               # ENOENT = hallucinated
which <name>                                  # empty if not in PATH
find /opt /var /home /etc -name "<name>" 2>/dev/null   # scoped, not /

# 2. Check if the action is actually a chat command in source
grep -rn "<name>" /path/to/source/            # router.exact / router.prefix = chat cmd
grep -rn "<name>" /path/to/source/templates/  # mentioned in prompt = model was told

# 3. Check the agent's prompt / template for hallucination fodder
cat /opt/<app>/templates/<relevant>.md        # see what the model was told
```

**If the action is a chat command, not a binary**:
- Tell the user they can type the chat command directly (e.g. `/dream-log` in feishu)
- Optionally add a one-line hint to the workspace's `SOUL.md` or equivalent user-editable file so the model suggests the correct invocation next time instead of inventing a shell path
- Optionally add a "DO NOT call `<path>` via `exec`" sentence to the relevant template

**If the action is truly a missing binary**:
- The bot probably needs a CLI tool installed; this is a deploy gap, not a hallucination
- Add it to the install script or systemd unit

The cost of skipping this check: hours of "investigation" chasing a phantom that was never there.

### 9. "The agent said it did X" — verify with concrete artifacts, not the journal

When debugging an LLM-driven system (chatbot, autonomous tool-caller, MCP
client), the agent's journal output is **the agent's self-report, not
ground truth**. A common LLM failure mode is to ANNOUNCE a plan, send a
response, and STOP — without ever invoking the promised tool. The journal
shows "I will do X" but no follow-up `Tool call: exec(...)` or `write_file(...)`
entries. To verify, cross-reference the agent's claims against the real
artifacts the work would have produced.

**Recipe — verify the agent actually executed:**

1. **Get the journal after the announcement**:
   ```bash
   journalctl -u <svc> --since "<announcement time>" | tail -30
   ```
   Look for any `Tool call: <name>(...)` entries AFTER the announcement
   text. If only "Response to <user>" follows, the agent ended the turn.

2. **Read the session JSONL** (path varies by framework):
   - nanobot: `<workspace>/sessions/<channel>_<user_id>.jsonl`
   - Hermes Agent: `~/.hermes/state.db` (SQLite + FTS5) or per-session JSON
   - PKB: `notes/*.md` in the GitHub repo

   Each entry has `role: tool | tool_calls: [{name, arguments}]`. An
   announcement followed by an assistant entry with `tool_calls: []` and a
   content field describing the next step is the smoking gun for
   "all talk no action".

3. **Check artifacts the work would have created**:
   - Files claimed to be written: `find /workspace -newer <announce_file> -type f`
   - Network endpoints claimed to be called: `cat /proc/net/tcp` for
     outbound ESTABLISHED connections to expected IPs
   - Background jobs claimed to be running: `ps -ef | grep <pattern>`
   - Config changes claimed to be made: `stat -c '%y %n' <config_file>`

4. **Compare timestamps**:
   - File mtime BEFORE the user message = hallucination, not action
   - File mtime AFTER the announcement but without matching tool_exec
     in journal = the LLM used `write_file` and the `write_file` tool
     produced no real file (silent failure)
   - Multiple file mtimes in the same second as the announcement
     = automated agent, not LLM

5. **Read the tool-results cache** (if available):
   - Some frameworks cache tool results: nanobot at
     `<workspace>/.nanobot/tool-results/<session_id>/call_<hash>.txt`
   - File mtime on these tells you when the call actually ran
   - Empty result files (0 bytes) = tool was called but the result was empty
   - Missing result files = tool was called but result wasn't cached = suspicious

**Concrete failure pattern from nanobot v0.2.1** (with vps-lite profile):

The agent said: "读取成功！我将开始配置并测试 Larksuite API..."
followed by 40 minutes of silence. The session JSONL's last entry was
`role: assistant, tool_calls: []` — the LLM turn ended with a promise
but no tool invocation. 0 outbound connections to `open.larksuite.com`
in `/proc/net/tcp`. 0 new files in `/tmp` owned by nanobot. 0 new entries
in journalctl. The agent's response was "I will do X" without "I did X".

**Fix pattern** — make the agent embed its execution in the same turn:
- Strengthen `SOUL.md` / `AGENTS.md` rules: "Never end a turn with a plan
  or promise. If you say 'I will do X', the first concrete step
  (write the file, run the tool, parse the result) must happen in the
  same turn."
- Show GOOD vs BAD examples in the agent's prompt
- Treat `继续`, `开始吧`, `试试看`, `ok` as "do the next step now"

**Caveat — `verification-before-completion` has the agent-side framing**
("don't claim success without evidence"). This section is the **inverse**:
"when monitoring an agent's claims, don't accept them without independent
verification". They are complementary halves of the same problem.

### 10. Tools with strong invariants — add a self-heal action, don't loosen the guard

**Pattern**: Some tools enforce hard invariants on the data they manage — file content must equal `delimiter.join(parsed_entries)` (round-trip invariant), file hash must match a stored reference, file must match a strict JSON schema, append-only log must not edit historical entries. When an external write (shell append, manual edit, patch tool, sister session, partial migration) breaks the invariant, the tool typically **refuses all future writes** with a vague error and locks itself until an operator manually repairs the file.

**The wrong fix** (operator instinct under pressure): bump the limit, loosen the check, or patch the file manually each time. This:
- Loses the safety property the invariant was designed for
- Doesn't help the next time drift happens
- Shifts the failure mode from "loud refusal" to "silent corruption"
- Repeated manual patches accumulate risk — each manual `sed` is one more chance to break something else

**The right fix**: add a `consolidate` / `repair` / `self_heal` / `reset` action to the tool. The action should:
1. **Backup the current file to `<file>.bak.<ts>`** BEFORE any mutation — no data loss even if the heal itself breaks
2. **Parse forgivingly** — tolerate whitespace drift, missing delimiters, missing `**bold**` titles, content added by patch/shell/manual
3. **Re-serialize in the strict invariant-required format** — so the round-trip check passes after the heal
4. **Trim over-limit entries with a visible marker** (e.g. `[...truncated by consolidate <ts>; original was NNNN chars...]`) — never silently drop content
5. **Atomic-write the repaired file** (temp + rename) so concurrent readers see old or new, never partial
6. **Update in-memory state** to match the new file (otherwise the next mutation may write stale data back over the heal)
7. **Return a summary** with before/after size, n_entries, n_trimmed, backup path, and the new round-trip status — the caller verifies the heal, doesn't trust it

**Why this pattern wins over loosening the invariant**:
- The tool becomes **self-recovering** instead of self-locking — the error is no longer terminal
- The invariant stays **strong** (re-asserted after heal) instead of weakened (gap-by-gap)
- The bot/operator can call the heal action **themselves** when they hit the error — no out-of-band intervention
- Backup-before-write means the heal itself is reversible
- Truncation markers keep the data **transparent** — operator can review and restore from the .bak if the heal dropped something important

**Resource-protecting limits are different from format drift — don't conflate them**:
- Format/structure drift (round-trip, schema, hash) → **self-heal** the file
- Resource limits (char count, token budget, RSS ceiling) → **respect them**, don't bump
- If the tool reports both at once (e.g. "format drift + over limit"), the self-heal fixes the format but the size check still applies — the bot must use `replace` to merge or `remove` to drop old entries, not add new ones

**Worked example** (memory_tool.py on a 1v1g VPS, 2026-06-22):

The tool had:
- `ENTRY_DELIMITER = "\n§\n"`, file content must equal `"\n§\n".join(parsed_entries)` exactly (round-trip)
- Per-entry char limit `2200` (system prompt size budget)
- Total char limit also `2200` (snapshot goes into every LLM call's system prompt)

An external shell append added a new entry without the `§` delimiter → file no longer round-tripped → tool refused all writes with `"Refusing to write MEMORY.md: file on disk has content that wouldn't round-trip through the memory tool"`. The bot tried `add` 5 times, all rejected, all generated `.bak.<ts>` files. The bot was effectively locked out from writing its own memory.

The user explicitly rejected the proposed fix of bumping the char limit: **"char 限制是考虑到了系统资源限制"** (the limit exists for system resource reasons — bumping it loses 1v1g memory budget and bloats every LLM call's prompt). The right fix was a self-heal action.

Patch: added `consolidate` action to the tool. It:
- Backed up the file
- Parsed forgivingly (using `**bold**` titles as entry boundaries when `§` was missing, stripping extra whitespace around `§`)
- Re-serialized in strict `"\n§\n"` format
- Trimmed only entries over the per-entry char limit (with `[...truncated by consolidate <ts>...]` marker)
- Atomic-wrote via temp + `os.replace`
- Updated in-memory `memory_entries` / `user_entries` to match

Result: format drift eliminated (`raw.strip() == roundtrip: True`), per-entry char limit enforced, total size limit still enforced (correctly). The bot could `add` again — but only after the total was under limit, which is the right behavior. The bot then decided what to `replace` / `remove` to make room, exactly as the size limit was designed to drive.

**Skip the write-approval gate for self-heal actions**: most mutating tool actions go through a write-approval gate to prevent the bot from making unexpected changes. The self-heal action is operator-initiated (or bot-initiated under explicit "you've hit a drift error, heal now" instruction) — gate it and you recreate the same lock. Let it bypass the gate and document why in the gate's exemption list.

**When NOT to add self-heal**: if the invariant protects against **user/operator mistakes** (e.g. "don't allow writes during a transaction", "this is a checksum-verified artifact, refuse any change"), self-heal could mask the mistake. In that case the right behavior IS to refuse — and the operator needs to handle it manually with explicit acknowledgment. Ask: "if this self-heal ran automatically and the operator didn't notice, what would break?" If the answer is "data corruption, compliance violation, audit gap" — keep the refusal.

**Diagnostic move** (Phase 1): when a tool's "refuse to write" error mentions "drift", "round-trip", "hash mismatch", "schema invalid", or "wouldn't round-trip", **don't patch the file manually first**. Read the tool's source to see if a self-heal action already exists. If not, propose adding one before doing anything else — manual file surgery at this stage is the most common way to make things worse (you fix the format, break the size; or fix the size, break the format; etc.).

### Phase 1 Completion Checklist

- [ ] Error messages fully read and understood
- [ ] Issue reproduced consistently
- [ ] Recent changes identified and reviewed
- [ ] Evidence gathered (logs, state, data flow)
- [ ] For async handlers with silent drops: trace added at every filter/branch, log inspected, drop point identified
- [ ] If a tool refuses writes due to invariant drift (round-trip / hash / schema): checked for a self-heal action before manual file patching (§10)
- [ ] Problem isolated to specific component/code
- [ ] Root cause hypothesis formed

**STOP:** Do not proceed to Phase 2 until you understand WHY it's happening.

---

## Phase 2: Pattern Analysis

**Find the pattern before fixing:**

### 1. Find Working Examples

- Locate similar working code in the same codebase
- What works that's similar to what's broken?

**Action:** Use `search_files` to find comparable patterns:

```python
search_files("similar_pattern", path="src/", file_glob="*.py")
```

### 2. Compare Against References

- If implementing a pattern, read the reference implementation COMPLETELY
- Don't skim — read every line
- Understand the pattern fully before applying

### 3. Identify Differences

- What's different between working and broken?
- List every difference, however small
- Don't assume "that can't matter"

### 4. Understand Dependencies

- What other components does this need?
- What settings, config, environment?
- What assumptions does it make?

---

## Phase 3: Hypothesis and Testing

**Scientific method:**

### 1. Form a Single Hypothesis

- State clearly: "I think X is the root cause because Y"
- Write it down
- Be specific, not vague

### 2. Test Minimally

- Make the SMALLEST possible change to test the hypothesis
- One variable at a time
- Don't fix multiple things at once

### 3. Verify Before Continuing

- Did it work? → Phase 4
- Didn't work? → Form NEW hypothesis
- DON'T add more fixes on top

### 4. When You Don't Know

- Say "I don't understand X"
- Don't pretend to know
- Ask the user for help
- Research more

---

## Phase 4: Implementation

**Fix the root cause, not the symptom:**

### 1. Create Failing Test Case

- Simplest possible reproduction
- Automated test if possible
- MUST have before fixing
- Use the `test-driven-development` skill

### 2. Implement Single Fix

- Address the root cause identified
- ONE change at a time
- No "while I'm here" improvements
- No bundled refactoring

### 3. Verify Fix

```bash
# Run the specific regression test
pytest tests/test_module.py::test_regression -v

# Run full suite — no regressions
pytest tests/ -q
```

### 4. If Fix Doesn't Work — The Rule of Three

- **STOP.**
- Count: How many fixes have you tried?
- If < 3: Return to Phase 1, re-analyze with new information
- **If ≥ 3: STOP and question the architecture (step 5 below)**
- DON'T attempt Fix #4 without architectural discussion

### 5. If 3+ Fixes Failed: Question Architecture

**Pattern indicating an architectural problem:**
- Each fix reveals new shared state/coupling in a different place
- Fixes require "massive refactoring" to implement
- Each fix creates new symptoms elsewhere

**STOP and question fundamentals:**
- Is this pattern fundamentally sound?
- Are we "sticking with it through sheer inertia"?
- Should we refactor the architecture vs. continue fixing symptoms?

**Discuss with the user before attempting more fixes.**

This is NOT a failed hypothesis — this is a wrong architecture.

---

## Red Flags — STOP and Follow Process

If you catch yourself thinking:
- "Quick fix for now, investigate later"
- "Just try changing X and see if it works"
- "Add multiple changes, run tests"
- "Skip the test, I'll manually verify"
- "It's probably X, let me fix that"
- "I don't fully understand but this might work"
- "Pattern says X but I'll adapt it differently"
- "Here are the main problems: [lists fixes without investigation]"
- Proposing solutions before tracing data flow
- **"One more fix attempt" (when already tried 2+)**
- **Each fix reveals a new problem in a different place**

**ALL of these mean: STOP. Return to Phase 1.**

**If 3+ fixes failed:** Question the architecture (Phase 4 step 5).

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Issue is simple, don't need process" | Simple issues have root causes too. Process is fast for simple bugs. |
| "Emergency, no time for process" | Systematic debugging is FASTER than guess-and-check thrashing. |
| "Just try this first, then investigate" | First fix sets the pattern. Do it right from the start. |
| "I'll write test after confirming fix works" | Untested fixes don't stick. Test first proves it. |
| "Multiple fixes at once saves time" | Can't isolate what worked. Causes new bugs. |
| "Reference too long, I'll adapt the pattern" | Partial understanding guarantees bugs. Read it completely. |
| "I see the problem, let me fix it" | Seeing symptoms ≠ understanding root cause. |
| "One more fix attempt" (after 2+ failures) | 3+ failures = architectural problem. Question the pattern, don't fix again. |

## Quick Reference

| Phase | Key Activities | Success Criteria |
|-------|---------------|------------------|
| **1. Root Cause** | Read errors, reproduce, check changes, gather evidence, trace data flow | Understand WHAT and WHY |
| **2. Pattern** | Find working examples, compare, identify differences | Know what's different |
| **3. Hypothesis** | Form theory, test minimally, one variable at a time | Confirmed or new hypothesis |
| **4. Implementation** | Create regression test, fix root cause, verify | Bug resolved, all tests pass |

## Hermes Agent Integration

### Investigation Tools

Use these Hermes tools during Phase 1:

- **`search_files`** — Find error strings, trace function calls, locate patterns
- **`read_file`** — Read source code with line numbers for precise analysis
- **`terminal`** — Run tests, check git history, reproduce bugs
- **`web_search`/`web_extract`** — Research error messages, library docs

### With delegate_task

For complex multi-component debugging, dispatch investigation subagents:

```python
delegate_task(
    goal="Investigate why [specific test/behavior] fails",
    context="""
    Follow systematic-debugging skill:
    1. Read the error message carefully
    2. Reproduce the issue
    3. Trace the data flow to find root cause
    4. Report findings — do NOT fix yet

    Error: [paste full error]
    File: [path to failing code]
    Test command: [exact command]
    """,
    toolsets=['terminal', 'file']
)
```

### With test-driven-development

When fixing bugs:
1. Write a test that reproduces the bug (RED)
2. Debug systematically to find root cause
3. Fix the root cause (GREEN)
4. The test proves the fix and prevents regression

## Real-World Impact

From debugging sessions:
- Systematic approach: 15-30 minutes to fix
- Random fixes approach: 2-3 hours of thrashing
- First-time fix rate: 95% vs 40%
- New bugs introduced: Near zero vs common

**No shortcuts. No guessing. Systematic always wins.**

## Reference Templates

- `references/self-heal-action-template.md` — reusable Python skeleton for adding a `consolidate`/`repair` action to any tool that enforces a strong invariant (round-trip / hash / schema). Companion to §10. Includes the forgiving parser, atomic-write pattern, dispatcher integration, verification recipe, and anti-patterns to avoid.
