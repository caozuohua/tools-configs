---
name: agent-response-critique
description: "Evaluate whether an AI agent's response (nanobot, another LLM, or even a past self) is genuinely reflective or confabulated. Cross-references the agent's claimed citations and attributions against actual logs/journal/source data to detect hallucinations, lucky workarounds, and 'plausible-sounding but wrong' diagnoses. Use when user says '判断下他的回复是否合理', 'evaluate nanobot', 'check if X really happened', 'is this agent's reasoning sound', or when an agent makes a specific claim (line numbers, cursor positions, error messages, file contents) that can be verified."
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [agent-analysis, llm-evaluation, hallucination-detection, log-verification, meta-cognition]
    related_skills: [gcp-vps-ops]
---

# Critique an AI agent's response against ground truth

## When to use

- Another agent (nanobot, a subagent, a remote Hermes, etc.) made a claim that can be **independently verified** against logs, journal, file contents, or other ground truth.
- The user asks "is this response reasonable?", "判断下", "evaluate", "check".
- An agent's response *looks* well-reasoned but you suspect hallucination, citation fabrication, or post-hoc rationalization.
- A workflow goes wrong and you need to attribute the failure (real bug? agent error? env quirk?) before designing the fix.

## The methodology (4 steps)

### 1. Identify the agent's *verifiable* claims

Agents often make responses that look reflective ("I tried X, found Y, did Z"). Pull out the specific factual claims:
- **Citations**: "I read X file at line 35-39" / "as documented in Y" / "the error was..."
- **Attributions**: "this is because X" / "the cause was Y"
- **Actions claimed**: "I updated SKILL.md" / "I called API Z"
- **References to evidence**: "history.jsonl shows..." / "log says..."

Separate these from the agent's *narrative* (the explanation, the moral of the story). The narrative can be plausible-sounding fabrication; the citations/attributions/actions are checkable.

### 2. Locate the ground truth

Pick the most specific claim and find the source of truth:
- **Logs**: `journalctl -u <service> --since "..."` on the remote system
- **File contents**: `read_file` / `cat` for files the agent claims to have read or written
- **Process state**: `ps`, `/proc/<pid>/stat`, `ss -tlnp` for claims about running services
- **API responses**: re-issue the same API call to verify what actually came back
- **Database rows**: `sqlite3 <db> "SELECT ..."` for claims about DB state
- **File diff**: `git diff` or `stat -c %y` for claims about "I just edited X"

The closer to the actual evidence, the better. An agent claiming "I read history.jsonl and saw X" is best refuted by reading history.jsonl yourself.

### 3. Cross-reference each claim

For each verifiable claim, compare what the agent *said* vs what the ground truth *is*:

| Agent's claim | Reality | Verdict |
|---|---|---|
| "cursor 35-39 contains X" | actual line 35-39 contains Y | hallucinated citation |
| "the error was `path outside working dir`" | actual log says "BLOCKED: sandbox policy" | wrong attribution |
| "I updated skills/qpc/SKILL.md" | file mtime is older than claim; updated skills/pkb/SKILL.md instead | action drift (target file differs from claim) |
| "I worked around by inlining the token literal" | `journalctl` shows multiple token refresh attempts; the final attempt did inline | partly true (got there by luck, not by stated reasoning) |
| "history.jsonl shows previous curl + Bearer pattern" | history.jsonl contains "Bearer" exactly 6 times, in different contexts | claim is vague, not directly falsifiable but worth probing |

### 4. Diagnose the *type* of inaccuracy (or accuracy)

Even a wrong claim can be useful — what kind of error is it?
- **Hallucinated citation**: invented a source that doesn't exist (e.g. "cursor 35-39")
- **Wrong attribution**: real symptom, wrong cause (e.g. redactor misattributed as path guard)
- **Action drift**: claimed to do A, actually did B (e.g. claimed qpc update, did pkb update)
- **Lucky workaround**: arrived at the right outcome by accident, can't reliably reproduce the reasoning
- **Right answer, wrong reasoning**: outcome correct but the stated logic doesn't match what actually worked
- **Genuine reflection**: claims line up with ground truth, reasoning is sound

This matters because the *fix* is different:
- Hallucinated citation → agent needs ground-truth access before claiming (give it logs, not vibes)
- Wrong attribution → debug the actual cause (don't optimize the supposed cause)
- Action drift → review/audit the agent's file edits before trusting them
- Lucky workaround → force the agent to formalize the pattern, don't trust the narrative
- Right answer, wrong reasoning → re-derive from first principles so future runs are reproducible
- Genuine reflection → trust and move on

## Red flags in agent responses

Patterns that warrant extra scrutiny before trusting the narrative:

- **Specific file/line references** ("line 35-39 of history.jsonl") — easy to hallucinate, hard to verify at a glance
- **Plausible-sounding error messages** quoted verbatim — agents often paraphrase or invent error strings when reasoning about cause
- **Causal chains** ("X happened because Y, which caused Z") — LLM causal reasoning is notoriously post-hoc
- **Self-narrating about own tool calls** ("I tried X but it was blocked, so I did Y") — may confabulate tool call histories to fit the story
- **References to specific files/tools/processes that sound right but aren't in the agent's actual context** — e.g. an agent mentions "the env file at /opt/.env" when no such file exists
- **Time/sequence claims** ("just before this", "earlier I did X") — temporal reasoning is unreliable in long contexts
- **"I learned that..."** updates to long-term memory without observable source — the agent may have decided to "remember" something it never actually verified
- **The "intelligent-sounding fix" that the user immediately suspected wasn't real** — if the user's gut says "this answer is too clean", verify before letting the agent proceed

## When NOT to apply

- Agent is producing creative output (writing, brainstorming, design suggestions) — no ground truth to check against
- Response is short and direct ("the file doesn't exist" / "I can't do X") — verify by re-trying
- Agent is asking a clarifying question — no claim to verify yet
- User is sharing the agent's response as documentation or evidence, not asking for evaluation

## Output format

When reporting the critique to the user, structure as:

1. **What's verifiable** (bulleted list of specific claims)
2. **What you checked** (which ground-truth source you consulted)
3. **What's right vs wrong** (a table or list per claim)
4. **What kind of error** it is (using the taxonomy above)
5. **What should happen next** (correct the agent's understanding? take a different action? trust and proceed?)

## Anti-pattern: don't reverse-engineer from a wrong claim

When an agent says "X is the cause", your first instinct may be to help them act on that diagnosis (e.g. design a workaround for "path outside working dir"). **Don't.** The diagnosis might be wrong; the workaround might not fix the real cause. Verify first, then act. If verification is hard, surface the ambiguity to the user rather than picking a side.

## Related

- `references/nanobot-case-2026-06-17.md` — a worked example of this
  methodology against nanobot's self-diagnosis response. Shows the
  exact pattern of journal-cross-reference + verdict table + diagnosis
  taxonomy in action.
- `gcp-vps-ops` — `journalctl` and `/proc/<pid>` access patterns
  for verifying claims about running services.
