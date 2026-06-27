---
name: incremental-audit-and-fix
description: |
  Load this skill when the user supplies an explicit per-file audit
  checklist AND asks for a strict one-task-at-a-time workflow with
  confirmation gates. Two-phase pattern: (1) read-only ✓/✗ audit
  pass against the user's criteria, with file:line quotes; (2) one
  fix per turn, shown as a diff, verified by actually running
  something, then wait for the next "继续" before proceeding.

  Trigger phrases: "按这个checklist来检查一遍", "逐文件列出 ✓ 正常 / ✗ 问题",
  "第一步：检查 / 第二步：补全", "每次只推进一个任务", "完成后等待确认",
  "只给 diff，不重复输出整个文件". Also load when the user gives a
  numbered gap list with "do them in order" semantics.

  Do NOT load for: pure one-shot bootstrap (no audit), pure refactor
  against a reference (no checklist), or "explain this code" — those
  have their own patterns.
---

# Incremental audit and fix

The user wants two things simultaneously:

1. **Coverage** — every file they listed, every criterion they gave,
   evaluated honestly. No silent skips, no padding.
2. **Control** — they drive the pace. You fix exactly one gap, then
   stop, then they say "继续" (or equivalent) before the next gap.

Satisfying one at the expense of the other fails the task.

## Phase 1 — audit (read-only, no modifications)

For each file the user listed, in their order, evaluate every criterion
they gave. Mark each as ✓ 正常 or ✗ 问题, quoting the file line/section
that satisfies or fails.

Output format per file:

```
## 📁 <relative/path.py>
- ✓ 正常：<criterion 1>（line X: <short quote from the file>）
- ✓ 正常：<criterion 2>（line Y: <short quote>）
- ✗ 问题：<criterion 3> — <specific description of what's wrong>
```

End with a "偏差 / 缺口" section listing everything that failed plus
any deviations the user's criteria didn't explicitly cover but you
noticed (e.g. "drive_reader has no `list_files` by that name; public
API is `iter_drive_files`").

Do NOT modify any file in Phase 1. Do NOT start fixing yet. Stop and
ask: "下一步是任务 N（<title>）— 继续？"

## Phase 2 — single fix per turn

When the user says go, fix exactly ONE gap. Per turn:

1. **Make the edit.** Show the diff only — never the full file.
2. **Verify it actually works.** Run an import, smoke test, CLI
   invocation, or `grep` against the criterion. Print the actual
   output, not a hand-wave like "should work".
3. **Summarize.** 1-2 bullets + 1-3 stats (files changed, LOC, etc).
4. **Stop.** Ask for the next gate, or wait silently.

Output format for a fix:

```
## Diff
```diff
@@ class Foo, line N @@
- old line
+ new line
+ new line
```

## Verification
```
$ uv run python3 -c "from foo import bar; bar()"
<actual stdout / stderr>
```

## Summary
- <one-line description of the change>
- <verification result with actual numbers>
```

## What "verify" means here

For a code change, verification must produce real signal:
- ✓ Smoke test that exercises the changed code path
- ✓ Import / `python -c "..."` that imports the new symbol
- ✓ CLI invocation of any new subcommand (`kb progress --help` etc.)
- ✗ "This should work because..." (no evidence)
- ✗ Unit test that doesn't actually run (just shows the code)

If verification requires an external service (GCP, Drive, Postgres)
and you can't hit it, say so plainly: "verify deferred — requires
real DB; smoke test below covers the code path that does NOT need
DB."

## Anti-patterns

- **Fixing during the audit.** Phase 1 is strictly read-only. If you
  spot a fix while auditing, write it as a deviation in the 偏差
  section, not a code change.
- **Bundling gaps.** "I fixed 1, 2, and 3 since they're related" — no.
  One gap per turn. The user controls the order.
- **Chaining pipeline operations without a checkpoint.** A pipeline run
  (`kb retry`, `kb ingest --reingest`, `kb reindex`, `migrate.py
  restore`, a full crawl, a batch ML eval) IS a fix in this workflow —
  it mutates shared state (DB rows, progress DB, API quotas, remote
  files). The user wants ONE pipeline op per turn, with results +
  audit + explicit "继续" before the next one. Running two retries
  in a row "because the first one revealed more issues" is a
  bundling violation, even if both are read against a checklist. The
  user can deny a long-running command mid-flight; treat that as a
  hard stop. Background-notify is fine for a single op, not a chain.
- **Full-file dumps.** The user said "只给 diff，不重复输出整个文件"
  for a reason. Their context is precious.
- **"Should work" claims.** Always run something. If you can't, say
  why explicitly.
- **"Should I continue?" after each gap.** Just stop. The user's
  working pattern is to say "继续" when ready; pre-asking wastes a
  turn.
- **Burying the diff.** Diff first, then verification, then summary.
  Don't open with prose that re-describes what the diff shows.
- **Skipping criteria because they "look fine".** Every criterion
  gets a ✓ with a line quote, even the obvious ones. The user
  can't verify what you didn't show.

## Edge cases

- **Criterion is ambiguous.** Pick the most literal interpretation,
  note the ambiguity in the audit, ask for clarification only at the
  end of the Phase 1 summary.
- **The user's criteria don't cover a real bug you see.** Note it in
  the 偏差 section with severity (low/med/high) so they can decide
  whether to add it to the queue.
- **A fix is blocked by an earlier gap.** Say so. Don't try to fix
  a later gap that depends on an earlier one — propose the right
  ordering and wait.
- **Verification genuinely needs a real service.** Run the code path
  you CAN test in isolation, and document the deferred parts.
- **The "fix" is a pipeline op, not a code change.** Some workflows
  have no source code to edit — the fix surface is the CLI itself
  (retry / reindex / delete / insert) and the verification is
  reading the resulting DB / progress / log state. Same rules apply:
  one op per turn, diff-style output (what you ran, what changed,
  stats before/after), and a stop + "continue?" before the next op.
  Pair ops with a `before` snapshot (e.g. `progress` + `stats`
  counts) so the user can audit the delta without re-running
  anything.
- **Operational boundary forbids the obvious fix.** If the user has
  a rule like "don't modify .env / config / remote code", surface it
  in the audit alongside any code/config-dependent deviation:
  "needs GEMINI_MODEL change in .env — outside my edit scope; user
  action required." Don't quietly work around it via shell env
  overrides and pretend the production config is fine.
