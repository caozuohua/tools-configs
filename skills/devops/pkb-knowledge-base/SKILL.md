---
name: pkb-knowledge-base
description: "PKB (Personal Knowledge Base) 个人知识库的架构、API、数据流和已知问题。Vercel + Supabase + Gemini embedding + JSONL 异地备份 (R2 可选)。DEPRECATED 2026-06-16 — 用户改用 Lark QPC Bitable 作为个人知识存储后端, 不要再写 PKB。本 skill 仅供历史查询/审计。"
---

# PKB Personal Knowledge Base

> **⛔ DEPRECATED 2026-06-16** — 用户明确说"不要写 pkb 了", 个人知识存储已切换到 **Lark QPC Bitable** ("QPC个人知识库", app_token `SDSewknVRiGvhOkD8F9jsA7opMh`, table_id `tblBF8uGRWFpCAnG`). 详见 `gcp-vps-ops/references/lark-api-write-via-remote-vps.md` 的 "QPC Bitable" 章节. **本 skill 只供历史查询/审计, 不要再写新数据到 PKB**. nanobot 5:05 dream cron 已自动清空 `nanobot_repo/skills/pkb/SKILL.md` (0 bytes).

> **状态**: 2026-06-12 完成 GitHub 镜像裁剪 — `notes.github_path` 列保留但不再写入, `pushToGitHub()` 退化为 no-op stub (待后续 PR 删除)。新写入永远 `url=""`。luck-agent 兼容性通过 `tests/contract/luck-agent.test.ts` 锁定。

## Architecture

- **Code**: `/opt/pkb/` (local), deployed at `pkb-self.vercel.app`
- **Repo**: `github.com/caozuohua/pkb` (private)
- **Stack**: Next.js 16 + Supabase (PostgreSQL + pgvector) + Gemini gemini-embedding-001 (768d) + JSONL 异地备份 (R2 可选, `/api/pkb/admin/export` 不依赖 R2 即可工作)

## Lib layout (post-2026-06-12-github-cut)

- `lib/auth.ts` — `withAuth()` middleware. `x-api-secret` header check, timing-safe comparison, fail-closed on missing env. **类型签名** `AuthedHandler` 返回 `Response | NextResponse` (不是单纯 `NextResponse`) 以支持流式路由, 见过 Next.js 16 `new Response(stream)` 模式的人会知道为什么, 见 `references/nextjs-16-gotchas.md`。
- `lib/notes.ts` — 业务核心。`saveNote`, `searchNotes`, `getNoteById`, `listNotes`, `updateNote`, `deleteNote`, `restoreNote`, `embedOneNote`, `embedPendingNotes`, `computeContentHash`, `inferNoteType`, `inferTopics`, `isValidUuid`, `normalizePkbSearchResults`, `buildPkbCreateResponse`。**导出 `getSupabase()`** (之前是模块私有, 给 `lib/backup.ts` 复用 lazy client)。
- `lib/backup.ts` — JSONL 流式 dump + parse。`iterateAllNotes()` (cursor 分页), `streamJsonlDump()` (manifest + 一行一 JSON), `parseJsonlDump()`。DUMP_VERSION 显式写在每行, 未来 schema 升级时拒绝旧 dump。
- `lib/r2.ts` — Cloudflare R2 客户端 (用 `@aws-sdk/client-s3`, R2 是 S3 兼容)。Lazy init, 4 个 env var (`CLOUDFLARE_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`) 缺一个就抛。`isR2Configured()`, `uploadToR2()`, `downloadFromR2()`, `buildDumpKey()`。
- `lib/responses.ts` — `ok()` / `fail()` envelope helpers. 每个响应都走这两个; 没有 inline `NextResponse.json({...}, {status: 401})` 漏出来。

## Data Flow

### Write (POST /api/pkb) — async pipeline (post-cut)
```
luck-agent → POST /api/pkb → saveNote(content) →
  ├─ Compute SHA-256 hash of normalized content
  ├─ Check existing hash → idempotent return if hit
  ├─ INSERT notes (with content_hash, embedding_status='pending')
  └─ after() callback (响应后跑):
        ├─ embedText(content) → embedding
        ├─ UPSERT note_embeddings
        └─ UPDATE notes SET embedding_status='done'/'failed'

响应 ~200ms 返回。**不再推 .md 到 GitHub** (commit 4c90c86 裁剪)。
```

### Read (POST /api/pkb/search) — hybrid
```
/pkb command → searchNotes(query) →
  ├─ Short query (<20 chars) → 跳过语义
  ├─ Long query: embedText → match_notes(0.65) → JOIN notes
  │   WHERE deleted_at IS NULL
  │   AND   embedding_status='done'
  └─ Fallback: ilike on content/summary/type, then topics contains, then tags contains
```

### Backup (POST /api/pkb/admin/backup) — 异地备份到 R2
```
触发源: 手动 curl / GitHub Actions cron (03:00 UTC daily)
  → streamJsonlDump() → 收集到字符串
  → uploadToR2(`pkb-dumps/YYYY-MM-DD.jsonl`)
  → 返回 { ok, note_count, key, bucket, bytes }

R2 未配置: 503 + 明确报错 (silent success 会让"备份失败"和"备份成功"看起来一样)。
R2 不可用但 `/admin/export` 永远可工作: 手工 curl 拉 JSONL 到本地。
```

### Restore
```
node --env-file=.env.local --import tsx scripts/restore-from-dump.ts <file.jsonl>
  → parseJsonlDump() → 批量 upsert by id (idempotent)
  → 触发 /embed-pending 重建向量 (对 embedding_status != 'done' 的行)
  → 软删除行的 deleted_at 保留
```

### Soft delete + restore
```
DELETE /api/pkb/:id           → UPDATE notes SET deleted_at=NOW()
                               (row + embedding 都保留, 软删除完全可逆)
POST   /api/pkb/:id/restore   → UPDATE notes SET deleted_at=NULL

Hard delete opt-in:
DELETE /api/pkb/:id?hard=true → DELETE FROM notes (级联 embeddings, **不再删 GitHub 文件**)
```

## Supabase Schema (2026-06-12 快照)

完整 SQL 见 `references/supabase-schema.md`。

**`notes` 表** (所有列):
```sql
id            uuid primary key default gen_random_uuid()
content       text not null
summary       text default ''
source        text default 'lark'
type          text default 'idea'
topics        text[] default '{}'
tags          text[] default '{}'        -- topics 的别名, update 时同步
github_path   text                       -- ⚠️ 死列, 不再写入. 保留仅为了 JSONL dump 的旧数据 round-trip. 计划 Phase 5 删.
content_hash  text                       -- SHA-256 of normalized content
deleted_at    timestamptz                 -- NULL = active
embedding_status text not null default 'done'  -- pending|processing|done|failed|skipped
created_at    timestamptz default now()
```

**索引** (post-soft-delete):
- `notes(content_hash) WHERE content_hash IS NOT NULL` — UNIQUE partial (幂等; NULL 不冲突)
- `notes(created_at DESC) WHERE deleted_at IS NULL` — partial, 覆盖所有活跃行读路径
- `note_embeddings(note_id)` — UNIQUE (支持 re-embed upsert)

**`note_embeddings` 表**:
```sql
id          uuid primary key default gen_random_uuid()
note_id     uuid references notes(id) on delete cascade
chunk_text  text not null
embedding   vector(768)  -- gemini-embedding-001, L2-normalized
created_at  timestamptz default now()
```

**`match_notes()` RPC**: cosine similarity, threshold 默认 0.65。

## 迁移文件

**`supabase/migration.sql`** — 给全新部署用的规范快照。**永远**包含所有 incremental 加过的列和索引。新加 migration 时, 同一个 commit 必须同步更新 `migration.sql`, 两者不漂移。

**`supabase/migrations/`** — 给已有部署用的 incremental 幂等文件。每个 `IF NOT EXISTS` 保护。已部署项目任意顺序跑都行 (幂等)。

| 文件 | 新增 |
|------|------|
| `supabase/migration.sql` | 完整 schema (新部署用) |
| `supabase/migrations/2026_06_12_content_hash.sql` | `content_hash` + partial unique + 幂等 backfill |
| `supabase/migrations/2026_06_12_soft_delete.sql` | `deleted_at` + `notes_active_idx` partial |
| `supabase/migrations/2026_06_12_async_embedding.sql` | `embedding_status` + `note_embeddings(note_id)` unique |

**未应用, 计划中**:
- `2026_xx_xx_drop_github_path.sql` — Phase 5 才做, 现在先留着兼容 JSONL dump 格式

**部署耦合警告**: 主分支代码可能引用某次 migration 加的列。先推代码后 migrate 会导致 API 500 (`column does not exist`)。**要么按住 push 等 migrate**, 要么**和 migrate 一起原子化 push**。

## API 端点 (10 routes, 8 dynamic)

所有受保护路由 (除 `/health`) 都需 `x-api-secret: <API_SECRET>`。不匹配 → 401。

### 响应信封 (所有端点通用)

成功 → `{ ok: true, ...payload }` (status 2xx)
失败 → `{ error: string, detail?: string }` (status 4xx/5xx)

`ok` 和 `fail` 在 `lib/responses.ts`。`ok: true` **永远**最后赋, 防止 caller 用 `{ok: 'overridden'}` 破坏成功合同。

### 端点清单 (10 routes)

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/pkb` | POST | 创建笔记. 幂等 (on `content_hash`). 响应含 `idempotent: true/false`. |
| `/api/pkb/search` | POST | 语义 + 文本混合搜索 |
| `/api/pkb/list` | GET | 分页列表 + 过滤 |
| `/api/pkb/health` | GET | 存活探针 (无 auth, 200/503) |
| `/api/pkb/embed-pending` | POST | Admin — 批量重 embed pending/failed 笔记 |
| `/api/pkb/admin/backup` | POST | 触发 dump → R2 (R2 缺凭证 503) |
| `/api/pkb/admin/backup` | GET | 健康检查: `{ r2_configured, version }` |
| `/api/pkb/admin/export` | GET | 流式下载 JSONL dump (不依赖 R2) |
| `/api/pkb/:id` | GET | 单条笔记 (404 if 软删除) |
| `/api/pkb/:id` | PATCH | 更新 content/type/topics/summary. content 改动触发 async re-embed |
| `/api/pkb/:id` | DELETE | 软删 (默认) 或硬删 (`?hard=true`) |
| `/api/pkb/:id/restore` | POST | 撤销软删. 幂等 |
| `/api/pkb/:id/embed` | POST | Admin 单条 re-embed |

### `url` 字段的合同 (luck-agent 关键约束)

`POST /api/pkb` 和 `POST /api/pkb/search` 的 `url` 字段**始终是 string**:
- caller 在 request body 显式传 `url` → 用 caller 的值
- 否则 → `""` (空串, 不是 null, 不是 undefined)

luck-agent 的 `_normalize_pkb_result_item` 用 `str(item.get("url") or "")` 读取, `format_pkb_result_items` 用 `if url:` 判断显示, **对空串都 graceful 处理, 不需要改 luck-agent 代码**。详细合同见 `docs/luck-agent-contract.md` (仓库内) 和 `tests/contract/luck-agent.test.ts` (15 个单测锁住)。

### List 过滤参数

`GET /api/pkb/list`:
- `limit` (1-100, default 50)
- `offset` (default 0)
- `type` — `notes.type` 精确匹配
- `topics` — 逗号分隔; 至少匹配一个 (PostgREST `overlaps`)
- `from` / `to` — ISO 8601 时间戳; `created_at` 闭区间
- `include_deleted` — boolean; `true` 时包含软删行

非法 `from`/`to` → 400 + 错误参数名。

### Search body

`POST /api/pkb/search`:
- `query` (string, 必填)
- `limit` (1-50, default 5)
- `source` (可选, 按 source 过滤)
- `action` (可选, 必须为 `"search"` if present; **死代码**, 没有任何 caller 传)

### Patch body

`PATCH /api/pkb/:id` (至少一个):
- `content` — 触发 async re-embed; status → `pending` → `done`
- `type`
- `topics` — 同步写 `tags` 列
- `summary`

### Delete

`DELETE /api/pkb/:id?hard=true` — 无 body。返回 `{ ok, deleted, mode }`。**永远 200**, 即便是 no-op (已软删或不存在)。

## Auth 模式

`lib/auth.ts` 导出 `withAuth(handler)` HOF。所有受保护路由都包一层:

```typescript
export const POST = withAuth<{ id: string }>(async (req, { params }) => {
  // handler body — auth 已验
})
```

- **时间安全比较** via `node:crypto.timingSafeEqual`. `===` 会按字节泄漏 secret.
- **Fail-closed**: 缺 `API_SECRET` env → 500 (不是 401). 缺 secret 是部署 bug, 不是客户端错误.
- **泛型** `<P>` 给 dynamic route `params` 提供类型.

## 单元测试

`npm test` 跑 86 个 vitest 单测, ~3s:
- `tests/lib/notes.test.ts` (44) — `inferNoteType`, `inferTopics`, `computeContentHash`, `isValidUuid`, `buildPkbCreateResponse`
- `tests/lib/responses.test.ts` (9) — `ok` / `fail` 信封不变量 (含 "caller 无法覆盖 `ok: true`")
- `tests/lib/auth.test.ts` (7) — `withAuth` 200/401/500 路径, 时间安全, fail-closed, env 隔离, context 透传
- `tests/lib/backup.test.ts` (12) — DUMP_VERSION, manifest, round-trip, parse 错误处理, cursor 分页
- `tests/contract/luck-agent.test.ts` (15) — **跨项目合同锁**: luck-agent 读的所有字段 + 类型 + `url` 始终是 string 的不变量

测试只覆盖纯函数. I/O 代码 (Supabase, Gemini) 通过对部署服务的 curl 验证. 见 `references/curl-verification-matrix.md`.

## Luck-Agent 集成 (2026-06-12 audit)

**luck-agent 用到的端点** (主项目) — 合同详见 `docs/luck-agent-contract.md`:
- `POST /api/pkb` (via `forward_to_pkb_result`, tool `write_pkb`)
- `POST /api/pkb/search` (via `search_pkb`, tool `search_pkb`)
- `GET /api/pkb/health` (lark 健康检查)

**Env vars (luck-agent 侧)**: `PKB_INGEST_URL`, `PKB_SEARCH_URL`, `API_SECRET` (正确值 `123123abcabc`).

**调用模式**:
- 写: `forward_to_pkb_result(content, note_type, topics)` → POST `{'content', 'type', 'topics', 'source': 'lark'}`
- 搜: `search_pkb(query, limit)` → POST `{'query', 'limit'}` → 读 `summary` + `results[].{title, content, topics, type, url, created_at}`
- health: 读 `{ok, supabase, hasApiSecret}`

**修改 PKB API 时的硬性约束** (luck-agent 不会自动跟进):
1. 不要删 luck-agent 读的任何字段
2. 不要改类型 (特别是 `url: string`, 永远不能变 null/undefined)
3. 新字段可以加, 不能改老字段
4. 改完跑 `tests/contract/luck-agent.test.ts`, 全过再 commit

**未接入 luck-agent 但已可用**:
- `GET /api/pkb/list` — 可对接 `/pkb list` 命令
- `GET /api/pkb/:id`, `PATCH /api/pkb/:id`, `DELETE /api/pkb/:id`, `POST /api/pkb/:id/restore` — 完整 CRUD
- `POST /api/pkb/embed-pending`, `POST /api/pkb/:id/embed` — admin tools

## 已知问题

1. **语义搜索阈值** — 0.65 (0.6 太松, 0.75 太严, 0.65 平衡精度/召回). 见 `lib/notes.ts` searchNotes().
2. **短查询降级** — <20 字符查询跳过语义, 走全文.
3. **Test 数据** — 2026-06-12 清理过 (21 条 test 笔记已删). **重做 test 数据要谨慎清理**. **更好**: 用 Vercel preview 部署做测试, 不污染 prod.
4. **Topics 多数为空** — `inferTopics()` 现在支持宽松匹配 (任何 `[A-Za-z]...` token, 不仅 `#hashtag`), 但 caller 显式传 `topics: []` 会覆盖推断结果. 见 `references/type-inference-regex.md`.
5. **content==title** — 碎片化灵感笔记天然如此. 区分: test 数据 → DELETE, 真碎片 → PATCH 补内容 + 加 topics.
6. **API_SECRET 不一致** — luck-agent .env 历史上配错过, 当前正确值独立验证. **不要动远程 .env.**

## Type Inference 细节

`inferNoteType()` 用**严格 regex 避免误判**英文词 "import" / "export" 在散文里. 完整 pattern 见 `references/type-inference-regex.md`.

`inferTopics()` 比 README 描述更宽松 — 任何 `(?:#|@)?[A-Za-z]...` token 都会被收集, 不只是 `#hashtag`. 1 字符 token 跳过 (除了 `AI`). 限制 5 个. caller 传 `topics: []` 显式覆盖推断.

## 搜索精度调优

- **match_threshold**: 0.65
- **短查询 bypass**: <20 字符跳过语义
- **语义搜索 JOIN notes**: 通过 `IN` 查完整数据
- **JOIN 过滤**: `deleted_at IS NULL` AND `embedding_status = 'done'`
- **回退链**: 语义 → ilike 全文 → topics contains → tags contains

## 批量操作 (Shell + API)

清理 / 批量更新 PKB 笔记, 用 curl + `x-api-secret`:

```bash
# 列出所有笔记 (可选过滤)
curl -s -H "x-api-secret: <SECRET>" "https://pkb-self.vercel.app/api/pkb/list?limit=100"
curl -s -H "x-api-secret: <SECRET>" "https://pkb-self.vercel.app/api/pkb/list?type=code&topics=python"
curl -s -H "x-api-secret: <SECRET>" "https://pkb-self.vercel.app/api/pkb/list?from=2026-06-10"

# 软删 (默认)
curl -s -X DELETE -H "x-api-secret: <SECRET>" "https://pkb-self.vercel.app/api/pkb/<ID>"

# 硬删 (不可逆)
curl -s -X DELETE -H "x-api-secret: <SECRET>" "https://pkb-self.vercel.app/api/pkb/<ID>?hard=true"

# 恢复软删
curl -s -X POST -H "x-api-secret: <SECRET>" "https://pkb-self.vercel.app/api/pkb/<ID>/restore"

# 重 embed 单条
curl -s -X POST -H "x-api-secret: <SECRET>" "https://pkb-self.vercel.app/api/pkb/<ID>/embed"

# 批量重 embed pending/failed
curl -s -X POST -H "x-api-secret: <SECRET>" -H "Content-Type: application/json" \
  -d '{"limit":50}' "https://pkb-self.vercel.app/api/pkb/embed-pending"

# 手动拉 JSONL dump (不依赖 R2)
curl -H "x-api-secret: $SECRET" -o pkb-dump-$(date +%F).jsonl \
     https://pkb-self.vercel.app/api/pkb/admin/export

# 触发 R2 dump
curl -X POST -H "x-api-secret: $SECRET" \
     https://pkb-self.vercel.app/api/pkb/admin/backup

# 更新 content + topics
curl -s -X PATCH -H "x-api-secret: <SECRET>" -H "Content-Type: application/json" \
  -d '{"content":"<new>","topics":["a","b"]}' \
  "https://pkb-self.vercel.app/api/pkb/<ID>"
```

**大规模清理用 `execute_code` + Python subprocess** — API 快 (100+ ops 无 rate limit). **更好**: 用 Vercel preview 部署做测试, 不动真数据库.

## 清理工作流 (preservation-first)

1. **列出**所有笔记 (查 `?include_deleted=true` 找孤儿) → 区分: 空壳 (content==title 或空) / test / 真碎片
2. **先删 test 数据** (标题含: test / 测试 / probe / delete_me / 排序测试 / type测试 等)
3. **修空壳碎片** — PATCH 补内容 (从 title 上下文推断) + 加有意义的 topics
4. **更新真笔记** — 修噪声太多的 topics (驼峰文件名当 tag → 规范小写)
5. **可选: embed-pending 扫一次** 补失败的 embed

Tips:
- 始终 `-H "x-api-secret: ..."` 走 header, **不走 query param** (否则 401)
- DELETE 返回 `{"ok":true,"deleted":true,"mode":"soft"}` 成功
- PATCH 只更新传入的字段; 不改的字段省略
- auth 问题排查: `curl -s -H "x-api-secret: <SECRET>" "https://pkb-self.vercel.app/api/pkb/health"`
- **优先用 Vercel preview 部署做测试** — 当前 `pkb-self.vercel.app` 是用户真数据

## Conventions (DOs and DON'Ts)

- **不要改远程机的代码/配置/.env** (运维规则, 包括 luck-agent 端)
- **用** `/opt/pkb/` 本地仓库做代码分析和理解
- 改 Vercel 部署需要仓库访问和重新部署

- **Preservation-first 清理**: user 说"清理"或"优化" PKB 时, **默认先审计 + 报告, 再删**. 真实碎片化知识 (即使短, 即使 content==title) 默认保留; 只有明显是 test 的才删. 不确定时倾向**恢复而非删除** — git history 和 Vercel 备份支持回滚, 别急着重删.
- **用 Vercel preview 做测试**: 当前的 `pkb-self.vercel.app` 是用户真数据. 用 Vercel preview 部署 (或独立 staging) 跑任何会 create/delete 数据的 curl 测试. 测试结尾是"验证笔记已创建"那种 = 污染了 prod.

## Async Embedding 运维手册

`embedding_status` 卡住时 (GEMINI_API_KEY 轮换后, Vercel 杀了 `after()` 回调等):

```bash
# 单次扫 50 条
curl -X POST -H "x-api-secret: $SECRET" -H "Content-Type: application/json" \
  -d '{"limit":50}' https://pkb-self.vercel.app/api/pkb/embed-pending

# 单条同步 re-embed
curl -X POST -H "x-api-secret: $SECRET" \
  https://pkb-self.vercel.app/api/pkb/<ID>/embed
```

**推荐**: `POST /api/pkb/embed-pending` 挂 Vercel Cron (5 分钟间隔, `limit: 50`) 自愈. 不挂的话, 一次 `after()` 失败 = 那条笔记从语义搜索消失, 直到手工 re-embed.

`embedding_status` 是判断"能不能搜到"的唯一信号. 笔记从语义结果里消失但内容看着对, **先看这列**.

## Supabase JS `.range()` 坑

**PostgREST 不认 `.range()` 之后的 filter.** 之前踩过: count 过滤了但 results 没过滤. 症状: `total: 60, results: 60 items, all type=idea` 当 filter `type=code` 时 (应该 0 命中). **filter 必须先于 `.range()`**:

```typescript
let query = getSupabase()
  .from('notes')
  .select('...', { count: 'exact' })
  .order('created_at', { ascending: false })

// 所有 filter 先
if (filters.type) query = query.eq('type', filters.type)
if (filters.topics) query = query.overlaps('topics', filters.topics)
if (filters.from) query = query.gte('created_at', filters.from)
if (filters.to) query = query.lte('created_at', filters.to)

// range() 必须最后
query = query.range(offset, offset + limit - 1)
```

重构后验证: 跑一个 curl 断言每个 result 真的匹配 filter, 不光看 count 对.

## (历史) Git 自动提交陷阱 — 已随 GitHub 裁剪解决

2026-06-12 之前, Vercel 在每次数据变更 (比如 `DELETE /api/pkb/:id`) 时**自动 commit 到 GitHub repo** (那是 GitHub 镜像的副作用). 本地分支会静默落后 `origin/main`. 如果你 `git reset --hard <parent-commit>` 再 `git pull --rebase`, **会丢所有 auto-commit 之间的文件** — 工作树里没救.

**症状** (2026-06-12 实测): cleanup 时 reset 到 943c89d (60 条) 然后 rebase 到 bc21e15 (15 条), 工作树只剩 19 条 — 45 个真知识文件丢了. 最后 `git checkout 943c89d -- notes/` 恢复再重 commit.

**裁剪后**: 这问题不存在了. 没有任何 Vercel 自动 commit 路径. 改 `pkb-self.vercel.app` 数据不会动 `github.com/caozuohua/pkb` 仓库. 这条保留为历史教训, 防止有人想恢复 GitHub 镜像时重蹈覆辙.

**仍要的 git 安全** (适用任何 auto-commit remote):
1. 永远 `git reset --hard origin/main`, 不要 reset 到 parent
2. `git checkout <historical-sha> -- <paths>` 只对特定路径
3. rebase/push 前先 `git log --oneline HEAD..origin/main` 看差异
4. 数字大幅分歧 → 检查 `origin/main` 是不是有 `delete:` / `add:` auto-commits

## See Also

- `references/cut-github-mirror-2026-06-12.md` — 裁剪 GitHub 镜像的完整决策链 + 合同 + 测试
- `references/backup-r2-restore-2026-06-12.md` — R2 dump + restore 脚本 + DR runbook
- `references/nextjs-16-gotchas.md` — 3 个 Next.js 16 行为 (下划线目录, withAuth 类型, 流式响应)
- `references/cleanup-2026-06-12.md` — bulk cleanup 流程和前后数据
- `references/api-evolution-2026-06-12-hardening.md` — 硬化 (auth, 信封, dedup, 软删, async embed, 测试)
- `references/supabase-schema.md` — 完整 SQL schema
- `references/type-inference-regex.md` — `inferNoteType()` 严格 regex + 为啥 substring 匹配会失败
- `references/api-evolution-2026-06-12.md` — 早期端点扩展和搜索调优
- 仓库内 `docs/luck-agent-contract.md` — 跨项目合同 (source of truth, 改前必读)
