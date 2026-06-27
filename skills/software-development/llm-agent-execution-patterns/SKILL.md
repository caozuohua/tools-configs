---
name: llm-agent-execution-patterns
description: Diagnose and fix LLM agents (Claude Code, Codex, nanobot, custom) that announce plans but fail to execute. Patterns for "act then report" behavior, proactive follow-through, treating verbs as actions, AND auditing the full prompt stack when a SOUL.md patch alone isn't enough. Use when an agent says "I will do X" but never does X, when the user has to push with "继续" / "do it now" to trigger work, or when investigating a framework's prompt architecture to find why the bot is structurally passive.
version: 1.1.0
platforms: [linux, macos]
metadata:
  hermes:
    tags: [llm, agent, prompt-engineering, execution, planning, behavior, anti-pattern, prompt-audit, soul-md, agents-md]
    related: [hermes-agent, claude-code, codex, opencode, agent-framework-design-analysis]
---

# LLM Agent Execution Patterns

## Overview

The "announce then stop" anti-pattern: LLM agents generate a plan or
announce an action in their response, then end their turn **without ever
calling the relevant tool**. The user has to push with messages like
"继续" or "你直接开始吧" to trigger actual execution.

This skill covers prompt patches, diagnostic steps, and verification
patterns for fixing the agent's system prompt so the **first concrete
step ships in the same turn as the announcement**.

## When to use

Triggers — any of these signals the anti-pattern:

- Agent says "I'll write a script" then stops — script never appears
- Agent says "Let me test this" then describes what the test would do
- User has to send "继续" or "你直接开始吧" to trigger work
- Multi-step plans where the first step never happens
- Verbs like "test", "verify", "check", "explore" get treated as plans
  instead of actions
- Session continuation: "继续" or "ok" feels ignored, agent re-explains
  the plan instead of doing the next step
- **After-failure permission trap (v2)**: agent runs command 1, gets a
  failure (command not found, missing config, wrong path), then asks
  "需要我跑吗?" / "should I run the diagnostic?" before running
  obvious read-only fallbacks like `ps`, `ls`, `cat`, `grep`. The
  agent recovers from the failure only after the user pushes again.
  Same anti-pattern as v1, wearing a different costume — "wait for
  permission to recover" instead of "wait for permission to start".

## Diagnose first

Confirm the bug exists by checking the session transcript:

```bash
# Look for "announce without tool call" pattern
grep -nE "I'll .*|let me .*|I will .*|我.*(来|去|准备).*(写|做|测)" session.jsonl | head -5

# Check tool_calls field in the same assistant turn
# (assistant turns with content but empty tool_calls = the anti-pattern)
```

Three signatures confirm the bug:

1. Assistant turn contains planning language ("I'll write", "let me prepare")
2. The same turn has zero `tool_calls`
3. User followed up with a "继续"-class message to push execution

## Fix: prompt patches

Add the following to the agent's `SOUL.md` (persona) or `AGENTS.md`
(project instructions) — both work; persona is stronger.

### Core rule (must have)

```markdown
- **Never end a turn with a plan or promise.** If you say "I will do X" or
  "let me Y", the first concrete step (write the file, run the tool, parse
  the result) must happen in the same turn. Multi-step tasks still proceed
  turn-by-turn, but the FIRST step always ships with the announcement.
  The user should never need to say "继续" or "开始吧" to trigger execution.
```

### Verb-as-action rule

```markdown
- **Verbs like "test", "verify", "check", "explore", "investigate", "try",
  "看看" are actions, not plans.** Your default is to actually invoke tools,
  not to describe what the test would look like. The first tool call goes
  in the same response as the announcement.
```

### Green-light user signals

```markdown
- **Treat user signals as green lights to act, not requests to plan more.**
  Phrases like "继续", "开始吧", "试试看", "你来", "ok", "嗯" all mean
  "do the next step now" — resume the prior task without re-explaining.
```

### Proactive follow-through (optional, for multi-step agents)

- When you start a task, think ahead: what does "done" look like? Try to
  complete the whole thing before reporting back. If you need to ask
  follow-up questions, batch them at the end — don't ping 5 times.
- When you hit an error: diagnose → propose the fix → try the fix →
  report what worked.
- **Read-only diagnostic fallbacks don't need permission.** When a tool
  call fails, run the next most likely read-only hypothesis yourself
  (`ps`, `ls`, `cat`, `grep`, `stat`, `env`, `find`, `which`,
  `command -v`, `read_file`). Only ask permission for destructive or
  irreversible actions (writes, deletes, service restarts, installs).
  *Line between proactive and over-cautious: does the next step
  change state?* Verified 2026-06-21 on `gcp-vps2` nanobot — the bot
  stopped at "需要我执行这些检查吗?" after `nanobot channels status`
  failed with "command not found". Patching the prompt to
  "read-only fallbacks run without asking" fixed it on the very next
  test (it ran `find / -name nanobot -executable` and recovered
  without re-asking). See
  `references/2026-06-21-nanobot-prompt-rewrite.md` tests 7 and 9.
- **After a tool call fails, run the next most likely hypothesis
  yourself.** Read-only diagnostic fallbacks (ps, ls, cat, grep, stat,
  env, find) don't need permission — only ask when the next step is
  destructive or irreversible. Asking permission for read-only
  fallbacks is over-caution. (v2 patch — see `references/nanobot-prompt-patch.md`)
```

## Diagnose the full prompt stack

If patching SOUL.md with the rules above doesn't fix the bot, the bug is probably **not a missing rule — it's a structural conflict across the agent's entire prompt stack**. Audit the full stack before patching:

1. **Find the system-prompt builder.** Open the agent's source for `build_system_prompt` / `build_messages` (e.g. nanobot's `nanobot/agent/context.py:81`, hermes-lite's equivalent). List the **order** in which prompt files are concatenated — later files override earlier ones. Persona files (SOUL.md) loaded as bootstrap AFTER identity/template files carry the most weight.
2. **Cross-check bundled template vs deployed copy.** Many agents (nanobot, hermes-lite, Codex/Claude Code) ship prompt templates that get copied to a workspace on first run. The deployed copy may have been edited, the bundled template may NOT have been. The fix belongs at the **source** level (the template in the repo) if you want fresh installs to be correct — patching only the deployed copy is a one-time fix.
3. **Audit each prompt file for behavioral rules.** For every file in the stack, look for:
   - **Permission-seeking rules** ("wait for confirmation", "ask first", "outline plans before acting")
   - **Conflicting core principles** (a positive rule + a negative rule that cancel each other — LLMs default to the more specific/conservative one when in conflict)
   - **Missing anti-pattern section** (rules that say what TO do but never what NOT to do — without a "do NOT" set the model self-generates plans, since planning is the safe default)
   - **Missing green-light signal mapping** (what does "继续" / "ok" / "嗯" mean to this agent? If unspecified, these trigger re-explanation of the plan)
4. **Check the memory/learning system.** If the agent has a "Dream"-like consolidation job that rewrites its own prompt files, verify the rules you're patching aren't being **rewritten out of existence** in the next consolidation cycle. Add [permanent] / [durable] tags on rules you want preserved.
5. **Test, don't speculate.** Send a probe message and watch whether the first response includes a tool call. If not, the patch didn't take effect — verify with `/status`, by reading the live system prompt, or by restarting the agent. Also: the rule "if a tool call fails, retry with a different approach" is usually present in `tool_contract.md` but is **never reinforced in the persona** — that's why bots report errors and wait instead of trying alternatives.

See `references/nanobot-prompt-stack-audit.md` for a worked example: 13 prompt files audited against 5 root-cause patterns on nanobot v0.2.1, including the build_system_prompt injection order.

## Why bots stay passive — 5 root-cause patterns

When the bug recurs after a prompt patch, the cause is usually one (or a combination) of these 5 patterns. Fixing only the first one is rarely enough:

1. **Explicit permission-seeking rule.** The persona file literally says "for multi-step tasks, outline the plan first and wait for user confirmation." Strongest form of the bug — direct instruction to wait. Fix: replace with the 3-rule act-then-report pattern above. **Symptom**: user always has to send "继续" / "开始吧" before any work happens.
2. **No anti-pattern section.** Persona has positive rules ("act immediately") but no negative examples ("BAD: describe without doing"). Without a "do NOT" set, the model self-generates plans since planning is the safer default. Fix: add a BAD vs GOOD example pair explicitly.
3. **No green-light signal mapping.** The model doesn't know that "继续" / "ok" / "嗯" / "你来" / "试试看" means "do the next step now". These trigger re-explanation of the plan instead of resumption. Fix: add the green-light rule (see Core rule patch text above).
4. **Error experience gets pruned.** The agent's memory consolidator (e.g. nanobot's Dream job, `consolidator_archive.md`) treats debugging steps as [ephemeral] and prunes them. The model never accumulates "last time error X was fixed by doing Y" across sessions — every error is a fresh first encounter. Fix: explicitly tag error-resolution facts as [permanent] / [durable] so Dream preserves them.
5. **Dream self-reinforcing feedback loop.** If the user keeps responding to the bot's "wait for confirmation" prompts with "好" (which Dream observes), Dream may infer "user values confirmation-style" and rewrite SOUL.md to be more conservative. The conservative rule then generates more confirmation prompts, creating a self-strengthening loop. Fix: never put "wait for X" rules in the persona, and teach the model to interpret "ok" as "go" so Dream observes proactive behavior, not confirmation compliance.

When patching, check for all 5 — the user's complaint "bot is passive, doesn't try to solve problems" usually maps to #1 (cause) + #4 (mechanism for not retrying) + #5 (why the patch keeps regressing).

## Pitfall: LLM conflict resolution favors the conservative rule

When a persona file contains two rules that conflict — e.g. "Core Principles: Solve by doing" + "Execution Rules: For multi-step tasks, outline the plan first and wait for user confirmation" — the model **does not** average them, blend them, or pick the more recent one. It picks the **more specific** and **more conservative** one. Specific wins because it has fewer escape hatches ("multi-step" is narrower than "tasks" in general). Conservative wins because waiting is the safer default (no risk of doing the wrong thing).

Practical implications for prompt design:

- **Don't have a "general ethos" rule and a "specific exception" rule.** Either commit to "always act first" or commit to "always ask first" — don't have both.
- **Patch attempts that ADD positive rules without REMOVING the conflicting negative rule don't work.** Verified on nanobot 2026-06-21: a deployed SOUL.md had 3 added lines ("Proactive tool usage is preferred...", "Proactively analyze data...") but kept the original "wait for user confirmation" rule. The model still waited. The added lines were read as aspirational; the specific rule was treated as binding.
- **Dream consolidation amplifies this.** If a [permanent] rule in SOUL.md says "wait", Dream won't touch it (correctly). But if the surrounding prose is "prefer proactive", Dream may reword it to be MORE conservative in the next cycle, not less.

The fix is structural: replace the rule, don't add to it.

## Worked example (BAD vs GOOD)

### BAD: announce then stop

```
User:  "试试看 Lark API"
Bot:   "好的，我来写脚本测试。请稍等。"  ← ENDS TURN, no exec call
User:  "继续"                                  ← user has to push
Bot:   "好的"                                  ← still no exec
```

This is a failure mode. The user shouldn't have to push.

### GOOD: announce + execute in same turn

```
User:  "试试看 Lark API"
Bot:   "好的，开始测试。"  [calls read_file("lark_credentials.json")]
       "读到 credentials，现在跑最小调用..."  [calls exec("curl ...")]
       "返回 401 — 需要补 offline_access scope"
```

## Verbs that mean "do now"

Apply to both LLM-agent-flavored English and Chinese. The Chinese side
isn't a strict translation — these are the colloquial verbs users
actually type in chat. Coverage of the most common ones is the
difference between "agent acts" and "agent asks":

| English | Chinese | Behavior |
|---------|---------|----------|
| test, verify, check, explore, try, investigate | 试试看, 验证, 检查, 探索, 看看 | invoke tool immediately |
| continue, start, go ahead, do, run | 继续, 开始, 来, 跑一下, 测一下 | resume / take first step |
| look, find, search, fetch, query | 看, 查, 找, 拉一下, 搜 | read / query immediately |
| then, next, after that | 接着, 然后, 再 | next step in sequence (no preamble) |
| yes, ok, yeah, mhm | 嗯, 好, 好的, ok | in mid-task: take the next step |
| I'll do X, let me Y | 我将, 我去, 我来 | first step in same turn |

**Why "看/查/找" matter**: in Chinese chat, the bare verb "看一下" or
"帮我查一下" is more common than English "check this out". Agents that
only know "check" / "verify" miss the colloquial cases.

**Why "接着/然后" matter**: in multi-step conversations, users use
"接着你 X" or "然后 Y" to chain. Agents should treat these as
sequential commands, not as new context.

## How to test the fix

**Don't stop at the first happy-path probe.** A 1-2 test pass can miss
critical failure modes — particularly the v2 after-failure permission
trap, which only surfaces when a command fails and the agent has to
decide whether to run a read-only recovery.

### Minimum 5-probe protocol (covers v1 + v2)

| # | Probe | Tests | Pass |
|---|---|---|---|
| 1 | "看下你的 SOUL.md" or "看下你的规则" | Self-knowledge, no preamble | Direct answer from system-prompt context, no redundant `read_file` call |
| 2 | "看下 30 分钟日志有没有 ERROR" | Act-then-report, honest calibration | `grep` in first turn; distinguishes "30min" vs "all-time" timestamps; labels inferences as such |
| 3 | "跑 `nanobot channels status`" (or any likely-to-fail command) | **v2 critical**: after-failure recovery | On failure, runs read-only fallback (`find` / `ls` / `ps`) without asking permission |
| 4 | "复盘一下之前那次失败的对话" | Bold hypothesis + verify | Lists 2+ hypotheses, verifies ≥1 with concrete data, gives 3-step improvement plan |
| 5 | "继续" (mid-task) | Green-light signal | Resumes prior unfinished task, doesn't re-explain plan |

### Per-test inspection (works for any nanobot instance)

```bash
# 1. Find the most recent session for the channel you tested
ls -lt /var/lib/nanobot/workspace/sessions/ | head -5

# 2. Print the last 4-6 entries with tool calls visible
sudo -u nanobot python3 -c "
import json
path = '/var/lib/nanobot/workspace/sessions/<session>.jsonl'
for line in open(path).readlines()[-6:]:
    d = json.loads(line)
    content = d.get('content', '')
    if isinstance(content, list):
        for c in content:
            if c.get('type') == 'text': content = c.get('text', ''); break
    tcs = d.get('tool_calls') or []
    print(f'=== {d.get(\"role\")} (tool_calls={len(tcs)}) ===')
    for tc in tcs:
        fn = tc.get('function', {})
        print(f'  TOOL: {fn.get(\"name\")}({str(fn.get(\"arguments\",\"\"))[:200]})')
    print((content or '')[:500])
    print()
"
```

**Pass criteria**:
- Test 1: `tool_calls == 0` for the final assistant turn (info was
  already in system prompt; bot correctly didn't redundantly read).
- Tests 2/3/4: the **first tool call** appears in the same assistant
  turn as the user message. No "好的我来..." preamble that ends
  without an exec.
- Test 3 specifically: the recovery tool call (after the failure) is
  also in the same turn. No "需要我..." permission ask between
  failure and recovery.
- Test 5: no plan re-explanation; the next tool call is a continuation.

**Probe budget**: budget ~5 minutes per round. After the v1 patch, run
all 5 probes before declaring success. If any fails, that's the next
v2-style gap to close.

If the bot still ends turns with plans, the prompt wasn't loaded —
verify by sending `/status` or whatever reveals the active system
prompt, or restart the agent.

## v2 patch (2026-06-21) — add the read-only fallback rule

The v1 patches above are necessary but **not sufficient**. After
deploying them on a real instance, one failure mode still slipped
through — and a too-shallow test pass would have missed it.

### The after-failure permission trap (discovered 2026-06-21 on gcp-vps2)

**Symptom**: agent receives a command, runs it immediately (v1 fix
works), but the command fails (`command not found`, missing config,
wrong path, etc.). The agent then stops and asks
"需要我执行这些检查吗?" / "Should I run the diagnostics?" before
running obvious read-only fallbacks like `ps`, `ls`, `cat`, `grep`,
`stat`, `env`, `find`.

This is the same anti-pattern as v1, wearing a different costume:
"wait for permission" is replaced by "wait for permission to recover."
The agent still doesn't complete the whole task in one turn.

**Real transcript (before v2)**:
```
User:  "跑 `nanobot channels status`"
Bot:   [exec nanobot channels status → command not found]
Bot:   "看来 nanobot 命令不在系统的 PATH 中……需要我执行这些检查吗?"
User:  ← has to push again to see the recovery
```

**Root cause**: v1's "Proactive Follow-Through" rule said "propose the
fix AND try it" — but only for permission/credential errors. Other
failure modes (command-not-found, wrong path, missing config) fell
into a gap where the agent defaulted back to over-caution.

**v2 SOUL.md addition** — append to "Bold Hypothesis, Careful
Verification":

```markdown
- **After a tool call fails, run the next most likely hypothesis
  yourself.** Read-only diagnostic fallbacks (ps, ls, cat, grep, stat,
  env, find) don't need permission — only ask when the next step is
  destructive or irreversible. Asking permission for read-only
  fallbacks is over-caution.
```

**v2 AGENTS.md addition** — append to "Proactive follow-through" (in
the Execution Patterns section):

```markdown
- **Read-only diagnostic fallbacks (ps, ls, cat, grep, stat, env, find)
  don't need permission when a prior command failed — run them.** Only
  ask permission for destructive / irreversible operations (writes,
  deletes, service restarts, installs). The line between "proactive"
  and "over-cautious" is whether the next step changes state.
```

### v2 verification protocol (the missing test cases)

The 4 v1 probes are necessary but not enough. v1 tests passed cleanly;
v2 surfaced only because of test #3 below. Add at minimum:

| # | Probe | What it tests | Pass criterion |
|---|---|---|---|
| 1 | "看下 SOUL.md" | Self-knowledge, no preamble | Reads content from system-prompt context, no `read_file` call (zero tool calls is correct here) |
| 2 | "看下 30 分钟日志有没有 ERROR" | Act-then-report + honest calibration | Calls `grep` first turn, distinguishes "30min" vs "all-time" timestamps |
| 3 | "跑 `nanobot channels status`" | **v2 critical test** | On failure, runs `find` / `ls` / `ps` without asking permission |
| 4 | "复盘之前那次失败的对话" | Bold hypothesis + verify | Lists 2+ hypotheses, verifies at least one with concrete data |
| 5 | "继续" (mid-task) | Green-light signal | Resumes prior task, doesn't re-explain plan |

**How to inspect any nanobot session result** (no special tooling — just
python3 + jsonl):

```bash
# 1. Find the most recent session for the channel you tested
ls -lt /var/lib/nanobot/workspace/sessions/ | head -5

# 2. Print the last 4-6 entries with tool calls visible
sudo -u nanobot python3 -c "
import json
path = '/var/lib/nanobot/workspace/sessions/<session>.jsonl'
for line in open(path).readlines()[-6:]:
    d = json.loads(line)
    content = d.get('content', '')
    if isinstance(content, list):
        for c in content:
            if c.get('type') == 'text': content = c.get('text', ''); break
    tcs = d.get('tool_calls') or []
    print(f'=== {d.get(\"role\")} (tool_calls={len(tcs)}) ===')
    for tc in tcs:
        fn = tc.get('function', {})
        print(f'  TOOL: {fn.get(\"name\")}({str(fn.get(\"arguments\",\"\"))[:200]})')
    print((content or '')[:500])
    print()
"
```

Pass = the first tool call appears in the same assistant turn as the
user message (no "好的我来..." preamble that ends the turn without
exec). For test #3 specifically, the recovery tool call must also be in
the same turn — no "需要我..." permission ask between failure and
recovery.

**v2 evidence (2026-06-21, gcp-vps2)**:

Test #3, before vs after the v2 patch:

```
BEFORE v2:                          AFTER v2:
[exec channels status]              [exec channels status]
[got: not found]                    [got: not found]
"需要我执行这些检查吗?" ← STOP    [exec find / -name nanobot]
                                    [got: /opt/nanobot/.venv/bin/nanobot]
                                    [exec <full-path> channels status]
                                    [got: real status table]
                                    "CLI 显示 ✗ 是因为没加载 --config"
```

After v2: 3 sequential tool calls in ONE turn, no permission ask.
The user did not have to send 继续.

### Where to put what (v2 update)

| File | v2 addition | Effect |
|------|-------------|--------|
| `SOUL.md` | 1 rule under "Bold Hypothesis, Careful Verification" | Persona: "failures trigger action, not permission" |
| `AGENTS.md` | 1 rule under "Proactive follow-through" in Execution Patterns | Operational: explicit "destructive vs read-only" line |
| `USER.md` | Optional — add "Don't ask permission for read-only fallbacks" | User-level reinforcement (Dream may rewrite within hours) |

SOUL.md is protected (per `Never delete: behavioral rules`) so the
persona rule survives. AGENTS.md is project-level and stable.
USER.md reinforcement is optional — Dream rewrites USER.md every ~2h
based on observed user behavior. The SOUL/AGENTS placement is the
durable fix.

## Where to place the patches

| File | Added section | Purpose | Effect |
|------|--------------|---------|--------|
| `SOUL.md` | Persona-level ethos (Execution Rules, Proactive Follow-Through, Honesty) | Strongest — loaded every turn |
| `AGENTS.md` | Project-level patterns (Execution Patterns with BAD/GOOD examples) | Strong — gives concrete templates |
| `USER.md` | User-specific facts (language, style, risk framing, project context) | Medium — Dream may rewrite parts |

**Prefer SOUL.md** for personality-level rules (the "act then report"
ethos), **AGENTS.md** for project-specific execution patterns (which
verbs count as "actions" in this codebase).

> **Caveat for SOUL.md and Dream consolidation** — some agents (e.g.
> nanobot) periodically run a "Dream" job that rewrites `USER.md` and
> `MEMORY.md` based on conversation history. `SOUL.md` is typically
> protected ("Never delete: behavioral rules"), so persona rules in
> `SOUL.md` survive. If you only put rules in `USER.md` they may get
> rewritten within hours.

## Internal Consistency (multi-file design rule)

When patching prompts across SOUL.md / AGENTS.md / USER.md (or any
multi-file prompt stack), audit for cross-file conflicts **before
deploying**. LLMs default to the more specific / more conservative
rule when instructions conflict, so any old "wait for confirmation"
line in SOUL.md will override new "act then report" lines in AGENTS.md
even if the new lines are added later. Verified 2026-06-21 on `gcp-vps2`
nanobot: a previous user attempt to fix the issue had added "Proactive
tool usage is preferred over mere confirmation of capabilities" to
SOUL.md, but the original "For multi-step tasks, outline the plan
first and wait for user confirmation" line was still present in the
same file. The bot kept waiting for confirmation — the new line was
overridden by the older, more specific one.

**Pre-deploy audit checklist** (do all 3):
1. **Grep for conflict pairs.** Search every prompt file for both
   sides of common contradictions:
   - "wait for confirmation" / "ask permission" vs "act then report" / "do now"
   - "be cautious" / "verify first" vs "be proactive" / "try first"
   - "polite / hedge" vs "direct / no preamble"
2. **Check layer alignment.** Persona rules (SOUL.md) and operational
   patterns (AGENTS.md) should reinforce, not duplicate. If SOUL.md
   says "be honest", AGENTS.md should give concrete templates for
   honest reporting, not redefine honesty. If they conflict, persona
   wins.
3. **User facts vs persona rules.** USER.md is for *who the user is*
   (language, time, preferences). Don't put persona rules there —
   they get Dream-rewritten. SOUL.md is for *how the agent behaves*,
   not for the user. Don't put user facts there.

**If the audit finds a conflict**: replace the old line in place
(using `patch` with `replace_all=false` to verify uniqueness) rather
than appending the new one. The LLM will see both and pick the
specific one. Verified 2026-06-21: replacing the offending line
shifted the bot from "always waits" to "always acts on multi-step
tasks" in the next test session.

## When to skip

- Agent already exhibits proactive execution — don't add rules that
  conflict with existing behavior, just verify
- User wants the agent to ask before acting (rare but valid for
  destructive operations) — keep the planning behavior
- Single-turn Q&A agent — execution patterns are irrelevant

## Diagnostic commands (cross-platform)

```bash
# 1. Find planning lines
grep -E "I'll|let me|I will|I'll write|我.*来.*(写|做|测)" session.jsonl

# 2. Check tool_calls field on those lines
python3 -c "
import json, sys
for i, line in enumerate(open('session.jsonl')):
    d = json.loads(line)
    if d.get('role') == 'assistant':
        has_plan = any(kw in str(d.get('content',''))
                       for kw in ['I will', \"I'll\", 'let me', 'I am going'])
        no_tool = not d.get('tool_calls')
        if has_plan and no_tool:
            print(f'line {i}: ANNOUNCE without TOOL_CALL')
            print(f'  content: {d[\"content\"][:200]}')
"

# 3. Count "继续" pushes from user (proxy for bug severity)
grep -c '"继续"\|"开始吧"\|"你来"' session.jsonl
```

If count > 0, the bug exists and is wasting user turns.

## See also

- `references/nanobot-prompt-stack-audit.md` — full 13-file audit
  on nanobot v0.2.1 with injection order diagram, file-by-file
  evaluation, 5 root-cause patterns mapped to specific lines, and
  the bundled-template vs deployed-workspace cross-check method.
- `references/nanobot-prompt-patch.md` — exact SOUL.md/AGENTS.md text
  that worked on nanobot v0.2.1 (vps-lite profile, Vertex AI
  gemini-3.1-flash-lite). **Includes v2 patch (2026-06-21)** with the
  read-only fallback rule + 5-probe verification protocol.
- `references/2026-06-21-nanobot-prompt-rewrite.md` — full 9-test
  Discord transcript with verdicts, the v2 patch text, and the
  internal-consistency lesson (when "added" lines conflict with
  existing rules, LLMs default to the more specific/conservative one).
  Use this as the canonical "did the patch work?" evidence.
- `references/discord-test-plan.md` — the 9-probe test plan with
  pre-flight, inspection commands, journal cross-check, and verdict
  scoring. Reusable for any agent with a Discord channel + journald
  service. ~10 min per round, budget 2 rounds.
  - `references/anti-pattern-transcripts.md` — more BAD/GOOD examples
    from real sessions
  - `references/nanobot-config-gotchas.md` — vps-lite config &
    runtime pitfalls (`modelPresets` required, `channels.X` is raw
    dict not pydantic, dict-vs-attr access pattern, journalctl
    namespace, "bot connected but silent" debug recipe)
  - `hermes-agent` — Hermes's `/goal` command is a related idea at the
    command level (long-running goal pinned in system prompt)
  - `agent-framework-design-analysis` — analyze WHY other frameworks
    chose their prompt patterns
  - `systematic-debugging` §5 — async event handler silent-drop
    technique, the foundation for debugging "agent connected but not
    responding" issues across all LLM agent frameworks
  - `nanobot-vps-deployment` — the operational layer (config, systemd,
    channels). Load this when the prompt-patch skill says "patch the
    prompt" but you also need to deploy the patch via sudo + base64.
