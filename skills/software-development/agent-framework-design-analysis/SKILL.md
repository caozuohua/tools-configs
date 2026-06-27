---
name: agent-framework-design-analysis
description: Analyze how a reference agent framework designed its prompts / tools / memory / deployment, and extract transferable lessons for your own agent project. Use when the user asks to study a foreign framework, mine design patterns, or "what can we learn from X". Distinct from codegraph (which maps structure) — this skill mines WHY each design choice was made, separates transferable from context-specific, and synthesizes to actionable principles.
---

# Agent Framework Design Analysis

Analyze a **reference** agent framework (a known-good implementation you're studying) and extract **transferable design patterns** for your own agent project.

The output is NOT "what the code does" — that is `codegraph`'s job. The output is **why each choice was made, what problem it solved, and whether/how to apply it to your own project.**

## When to use

- "Analyze how X designed Y" (prompts, tools, memory, deployment)
- "Study Z's architecture"
- "What can we learn from W"
- "Compare our agent design to X"
- "What design patterns should we adopt from Y"

## When NOT to use

- "Explain how X works" → that's `codegraph` (structural mapping) or a docs read
- "Find bugs in X" → that's `dogfood` or `systematic-debugging`
- "Port X to our codebase" → that's a `plan` workflow, not analysis
- One-off narrative requests ("summarize what X does")

## Workflow

Five phases. The first three are read-only; the last two are synthesis.

### 1. Foundation scan (use `codegraph` for this)

Before asking "why", confirm you understand "what":

- File tree + entry points
- Key abstractions (Tool, AgentLoop, ContextBuilder, etc.)
- Where the framework's "kernel" lives (immutable) vs "userland" (editable)
- A glossary of 5-10 internal terms

**Skip the rest of this skill if you can't articulate the framework's shape in 5 sentences.**

### 2. Identify the design questions

List the **5-10 hardest design questions** any agent framework must answer:

- How is the system prompt structured and what's stable vs changing per turn?
- How are tools exposed to the model and how is "use the right tool" enforced?
- How is untrusted input (web fetch, user content, subagent results) defended?
- How is memory persisted and routed (long-term vs scratchpad vs session)?
- How are multi-step / multi-turn loops bounded (iterations, retries, recovery)?
- How is state-machine plumbing (retry / continue / finalize) kept out of the prompt?
- How are capability constraints enforced (which role gets which tool)?
- How is prompt cache hit rate engineered (cost)?

For each question, find the framework's answer. **Don't just describe it — also describe what problem the answer is solving.**

### 3. Trace the rationale for each design choice

For each interesting choice, ask:

- **What cost or risk is this choice avoiding?**
- **What invariant is being preserved?**
- **What failure mode is being prevented?**
- **What's the alternative that was rejected, and why?**

Examples of good rationale mining:

| Choice | Bad description | Good description |
|---|---|---|
| System prompt split into static + bootstrap | "It has identity.md and SOUL.md" | "Identity is cache-stable (changes break Anthropic prompt cache); SOUL is Dream-managed (changes don't break cache). The split separates upgrade path from user-editable path." |
| Tool description with "Use X for Y, not Z" | "Tool descriptions are detailed" | "Tools reference each other bidirectionally. LLM sees N independent schemas; only description wording creates routing. Without cross-references, model has 20-30% lower tool selection accuracy." |

### 4. Categorize: transferable vs context-specific

For every pattern found, label it:

- **Transferable**: the principle applies to any LLM agent system, regardless of framework
  - Example: "description as routing table" — works in OpenAI, Anthropic, Google, local models
- **Context-specific**: only makes sense given this framework's specific constraints
  - Example: "Lark WebSocket long connection" — only relevant if you use Lark
  - Example: "pydantic-settings env var resolution with `${VAR}` syntax" — only relevant if you use pydantic-settings

**Be honest about which is which.** A common failure is to call something "a great pattern" when it's actually just nanobot's solution to nanobot's problem.

### 5. Synthesize to actionable principles

Compress the transferable patterns into a form the user can pin to the wall.

Recommended output shape (mobile-friendly, Discord-friendly):

- **5 core principles** (each with a 1-sentence "what" + 1-sentence "why")
- **3 bonus patterns** (less critical, more situational)
- **1 mnemonic one-liner** that captures the whole thing

The mnemonic should fit a tweet. Examples:
- "会变的别写死，骗人的打标签，工具互相对话，错误教人改。" (16 chars)
- "Stable system, dynamic tail, defend by omission, teach in errors."

If you can't make a tight mnemonic, the principles aren't sharp enough.

## Output format

For Discord mobile (matches the user's preferred format — see `discord-mobile-formatting` skill):

- Bullet lists only, no tables (tables render poorly on mobile)
- Each section: short heading + 1-3 line bullets
- Code/JSON examples inline, fenced only when essential
- End with the one-liner mnemonic as a callout

## Pitfalls

- **Don't transplant blindly.** A pattern is "transferable" only if you can name what invariant it preserves in YOUR context. If you can't, it's still nanobot-specific.
- **Don't describe WHAT, find WHY.** A list of files and abstractions is a codegraph output, not a design analysis. The value is in the rationale.
- **Don't over-attribute cleverness.** Some patterns are industry standard, not nanobot's innovation. Don't credit the framework for things every framework does.
- **Don't dump everything.** Synthesis matters. If you have 20 patterns, the synthesis failed. 8 is the right ceiling.
- **Don't ignore "what's NOT there".** Absent patterns are informative. Why doesn't nanobot have X? Because of Y constraint, or because Y is implicitly handled by Z?
- **Don't forget the cost model.** LLM systems have unusual cost dynamics (cache, token-burn, model call count). Many "clever" design choices exist purely for cost. Always ask: what does this save?
- **Don't forget the attack surface.** Prompt injection is a unique threat. Always ask: where does untrusted content enter, and how is it tagged or sandboxed?

## References

- `references/llm-prompt-design-principles.md` — the 8 core principles extracted from analyzing nanobot's prompt architecture (cache, tool routing, error teaching, defense by omission, etc.)
- `references/tool-prompt-routing.md` — the 5 patterns for writing tool descriptions that build a routing graph
- `references/synthesis-templates.md` — output templates for the 5+3+1 mnemonic shape and other synthesis forms
