# Luck-Agent Architecture Reference

## Codebase Layout (`/opt/luck-agent/`)

```
luck-agent/
├── agent.py              # Entry point — boots config, memory, tools, handlers
├── config.py             # Global config (env-driven)
├── core/
│   ├── memory.py         # SQLite persistence (WAL mode) — messages, user_profile, goals, lessons
│   ├── intent_router.py  # Zero-AI rule-based intent routing + tool subset selection
│   ├── execution_engine.py   # Generic step execution loop (state machine)
│   ├── supervisor.py     # Step review: pass/retry/fail/block
│   ├── model_router.py   # Multi-model routing with fallback
│   ├── task_queue.py     # Runtime task queue
│   ├── scheduler.py      # Cron/interval task scheduling
│   ├── protocols.py       # 2.0 structured JSON protocol (Goal, Step, ToolResult)
│   ├── goal.py           # Goal data class
│   └── topics.py          # Tag normalization
├── handlers/
│   ├── message.py        # ReAct tool-call loop + PKB integration
│   ├── command.py        # Slash command router (/mem, /pkb, /sh, /status, etc.)
│   └── file_handler.py   # Image/file/audio handling via Feishu bridge
├── skills/
│   ├── router.py         # Intent → skill dispatch
│   └── base.py           # Skill base class
├── runtime/
│   ├── worker.py         # Queue consumer — picks up goals, executes steps
│   ├── runtime_manager.py    # Runtime state + notification
│   ├── events.py         # Runtime event data class
│   └── notifications.py  # Feishu/Lark card sending
├── tools/
│   ├── github_tools.py   # GitHub API via gh CLI
│   ├── shell_tools.py    # Shell execution + file manager
│   ├── search_tools.py   # Web search
│   └── file_bridge.py    # Feishu file upload/download
├── controllers/
│   └── blog_controller.py    # Blog write/deploy workflow
└── cards/
    └── builder.py        # Feishu/Lark card JSON builder
```

## Request Flow

```
User Input → agent.py → intent_router (rule-based)
  → tool subset selection + prompt_hint
  → model_router (pick model, build system prompt)
  → ReAct loop (model → tool_call → inject result → repeat)
  → handlers execute tools (github/shell/search/pkb/memory/schedule)
  → send reply card
```

## Memory System (SQLite, WAL mode)

Tables in `memory.db`:
- `messages` — conversation history (user/assistant/tool)
- `user_profile` — KV store: preferences, rules, PKB integration
- `tasks` — task records (github_action/shell/file/agent)
- `goals` + `goal_steps` — Goal Runtime (long-running tasks)
- `runtime_events` — observability events
- `lessons` — Supervisor error patterns + solutions
- `kv_store` — system-level config
- `scheduled_tasks` — cron/interval job definitions
- `error_log` — structured errors
- `github_history` — GitHub action log
- `success_patterns` — tool call patterns injected into prompt

## PKB (Personal Knowledge Base) — External API

Vercel-hosted, **GitHub-backed** (not Supabase). NOT in memory.db.

- **Search**: `POST /api/pkb/search` with `{query, limit, source, action}`
- **Ingest**: `POST /api/pkb` with `{content, type, topics, source}`
- **Auth**: `x-api-secret` header
- **Note types**: `idea`, `question`, `fact`, `practice`
- **Storage**: Notes are `.md` files in `caozuohua/pkb/notes/` GitHub repo. `health` returns `supabase: true` but that refers to the V0 project, not PKB
- **No full-list endpoint** — must search with keywords and dedupe client-side
- **Note fields on write**: title, content, type, topics, url, created_at, id
- **Note fields on search**: title, content, type, topics, created_at (NO id, NO url)
- **No DELETE/PUT** — API is POST-only for data. Delete via GitHub repo directly
- **Topics pollution**: search index tokenizes content, so `topics` may include query words, not just stored tags

## Key Design Decisions

- **WAL mode**: Allows concurrent reads while writing; SQL changes take effect immediately
- **Rule-based intent router**: Zero LLM cost for classification; keyword + regex matching
- **Tool subset injection**: Only 3-5 tools per intent (not all 20+), reducing model confusion
- **Skill architecture**: Skills wrap controllers; router dispatches by intent
- **Feishu/Lark native**: Card-based replies, not plain text
