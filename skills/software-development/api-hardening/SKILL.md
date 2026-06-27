---
name: api-hardening
description: |
  Cleanup and hardening pass on an existing deployed API service — extract
  auth middleware, add defense-in-depth validation, ship bug fixes surfaced
  by the refactor, verify with a curl matrix post-deploy. Also covers
  "phased feature cut" workflows after a backup/feature audit concludes
  "remove X" — discovery, safety net, decision gates, surgical removal.
  Use when the user has a P0/P1/P2 issue list, says "好，继续" or "next P0"
  after a P0 fix, wants to harden a small TypeScript/Next.js/Fastify API
  on Vercel/Netlify/Railway, or asks to deprecate / cut / remove a
  feature while keeping consumer contracts intact.
  Triggers: "清理", "重构", "加固", "fix the API", "improve the service",
  "ship the next P0", "裁剪 X", "去掉 X", "下掉 X", "deprecate X",
  "remove X", "stop using X", "X 还在用吗?", "is X really necessary?",
  "backup strategy review", "注意 X 用到的接口不要挂".
---

# API Service Hardening

A repeatable pass for cleaning up an existing REST/JSON API that's
already deployed and serving real traffic. Optimised for single-author
services on Vercel-style platforms with a type-safe stack (Next.js
App Router, Fastify, Express + TS).

## When to use

- A P0/P1/P2 issue list exists (drafted by you from `codegraph` output
  or by the user)
- Service has duplication (e.g. auth checked inline in 5+ routes)
- A pre-existing bug surfaces during refactor and the user wants it
  shipped in the same commit series
- User says "好，继续" after a P0 fix — they want the next priority
  item, not a discussion of options

## When NOT to use

- Building a brand-new service (no existing behaviour to preserve)
- Refactor that requires DB schema change (use a migration skill)
- Pure performance work — measure first, different playbook
- User asked for a single targeted change, not a sweep

## Pre-flight: backup & dual-write audit

Before drafting the issue list, ask: **does this feature even
need to exist?** The most impactful hardening work isn't
tightening auth or fixing validation — it's removing a
"backup" or "mirror" that's silently drifting and creating
bugs. The user often already half-suspects this; an audit
gives them the data to act on.

Audit framework — five steps (see
`references/backup-strategy-audit.md` for the worked PKB
example):

1. **Enumerate data locations.** For every data type, list
   every store (DB, cache, Git, S3, log). Distinguish "source
   of truth" from "derived view".
2. **Map failure modes.** For each derived view: what
   happens when the write fails silently? When the read
   goes stale? When a deletion in the source doesn't
   propagate? **Most dual-writes have silent push failures**
   — the user sees a successful response, the "backup" was
   never written.
3. **Map DR scenarios.** What data is lost if X dies?
   What's the recovery path? Express each scenario in
   RPO (data loss tolerance) and RTO (recovery time).
4. **Calculate ROI.** Cost of keeping the feature
   (latency, code complexity, silent bugs) vs cost of
   replacing (one-time migration + new code). List the
   issues the dual-write causes and rank by leverage.
5. **Recommend with reasoning.** "Remove X, replace with Y"
   beats "fix the 7 bugs in X" if the cost analysis favours
   removal. Frame as a single decision, not a long debate.

The classic trigger phrases from the user: "X 还在用吗?"
(Is X still needed?), "备份策略审视下" (audit the backup
strategy), "这个功能是必要的吗?" (is this feature really
necessary?). When the user asks these, the answer is
frequently "no, it isn't — here's what should replace it."

The "GitHub mirror" pattern is a textbook case. It feels
like a backup but it isn't — push failures are silent, the
mirror drifts on PATCH (most PATCH paths don't sync), the
most expensive data (embeddings) isn't mirrored, and the
mirror costs 1+ second of save latency. The right answer is
usually **single source of truth + periodic full export**,
not dual-write.

If the audit concludes "keep it", that's fine — proceed to
the Workflow below with the dual-write as a known cost. If
it concludes "remove it", the Workflow shrinks dramatically
(bugs in dead code don't ship).

## Workflow

### 1. Prioritise the issue list

Group every issue into P0/P1/P2. **Within P0, do the highest-leverage
item first** — extracting auth middleware unblocks 5 routes;
deleting a dead route is a single file.

- **P0** — security, correctness, dead code, 5+ duplicates
- **P1** — quality wins: filtering, soft delete, dedup, rate limit
- **P2** — nice-to-haves: async, tests, caching

### 2. For each P0: extract, don't rewrite

When you find duplication (5 routes checking the same header), **extract
to a single helper**. Do not rewrite the route logic.

- Pick the cleanest location (`lib/auth.ts`, `lib/validation.ts`)
- Keep the public handler signature identical so existing callers
  don't break
- Use generics for type-safety across routes with/without dynamic
  params

### 3. Add defense-in-depth validation

When a bug surfaces (invalid UUID → 500), fix it in two places:

- **Handler layer** — return clear 400 with a meaningful error message
- **Lib layer** — guard with a strict check, return null/false so
  future internal callers also can't crash

This protects future internal callers you don't control yet.

### 4. Verify the diff before push

- `tsc --noEmit` (or equivalent) — 0 errors
- `next build` (or equivalent) — succeeds, all routes registered
- Lint, any unit tests that exist

### 5. Push and wait for deploy

```bash
git push origin main
# poll the health endpoint until 200
for i in {1..10}; do
  sleep 8
  code=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL")
  if [ "$code" = "200" ]; then break; fi
done
```

### 6. Curl verification matrix

For every P0, build a matrix covering:
- The new behaviour (e.g. invalid UUID → 400)
- The unchanged behaviour (e.g. valid UUID → 200/404)
- The auth boundary (no secret → 401)
- A regression case

Run as a single script. See `references/curl-verification-matrix.md`
for the reusable template.

## Key patterns

### Timing-safe auth comparison

```typescript
import { timingSafeEqual } from 'node:crypto'

function safeEqual(a: string, b: string): boolean {
  const aBuf = Buffer.from(a, 'utf8')
  const bBuf = Buffer.from(b, 'utf8')
  if (aBuf.length !== bBuf.length) return false
  return timingSafeEqual(aBuf, bBuf)
}
```

`===` leaks the secret byte-by-byte via response latency. Always
use `timingSafeEqual` for credential comparison.

### Fail-closed auth middleware

```typescript
export function withAuth<P>(handler: AuthedHandler<P>): AuthedHandler<P> {
  return async (req, ctx) => {
    if (!process.env.API_SECRET) {
      // 500, not 401 — missing env var is a deployment bug, not
      // a client error.
      return NextResponse.json(
        { error: 'Server misconfigured' }, { status: 500 }
      )
    }
    if (!safeEqual(req.headers.get('x-api-secret') ?? '', process.env.API_SECRET)) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }
    return handler(req, ctx)
  }
}
```

### Defense-in-depth UUID validation

```typescript
// Strict UUID v1-v8, standard variant. Rejects nil UUID by design
// (RFC 4122/9562 — version 0 is reserved for the nil UUID itself).
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
export function isValidUuid(value: unknown): value is string {
  return typeof value === 'string' && UUID_RE.test(value)
}

// Lib layer: return null, never throw
export async function getNoteById(id: string) {
  if (!isValidUuid(id)) return null
  // ...
}

// Handler layer: explicit 400 with clear message
function parseIdOr400(id: string | undefined): string | NextResponse {
  if (!id) return NextResponse.json({ error: 'id required' }, { status: 400 })
  if (!isValidUuid(id)) return NextResponse.json(
    { error: 'invalid id format (expected UUID)' }, { status: 400 }
  )
  return id
}
```

### Parse-or-return-400 helper pattern

A helper that returns either the parsed value OR a `NextResponse`
to return immediately, so the handler reads as flat happy-path code:

```typescript
const idOrError = parseIdOr400(id)
if (idOrError instanceof NextResponse) return idOrError
const id = idOrError  // narrow to string
```

Avoid deep nesting; flatten with early returns + type narrowing.

## Pitfalls

- **Don't write a fresh README unless asked.** The user often has a
  partial README and just wants sync. Confirm scope before doing a
  full rewrite.
- **Don't push orphan-route-removal in the same commit as the main
  refactor.** Each P0 should be its own commit for easy revert.
- **Don't trust the existing test suite as gospel.** Many tests
  use `https://example.com` as a mock URL and don't exercise the
  real API. Verify by hand with curl.
- **Inline `SECRET=***` in bash gets redacted by the LLM gateway.**
  Use a `.secret` file with `chmod 600` and `$(cat .secret)` instead.
  See the references file for the Python wrapper pattern.
- **TypeScript errors in `.next/dev/types/` after a route deletion**
  mean the build cache is stale. `rm -rf .next` and retry.
- **Vercel deploy can be fast (< 1s if no code change since last
  build) or slow (30+s for a real change).** Don't assume 1×8s is
  enough — keep polling.
- **Don't refactor and rewrite the README in the same commit series
  unless the user asked for both.** Two different concerns, two
  different reverts.
- **Cross-porting is not symmetric.** A fix in `lib/notes.ts` may
  apply to `lib/users.ts` too — but check the callsite shape first
  (handlers and other lib functions may differ).
- **`next build` cache hides type errors.** Always `rm -rf .next`
  after deleting a route, then rebuild.
- **Supabase JS `PostgrestBuilder` drops filters applied after
  `.range()`.** PostgREST does not honour filters on the range
  clause. Always put `.eq()`, `.overlaps()`, `.gte()`, `.lte()`,
  `.is()`, `.contains()` BEFORE `.range(offset, offset+limit-1)`.
  Symptom: `total` and `count: 'exact'` reflect the filtered count
  (Supabase REST computes count after the WHERE), but the response
  `results` array contains the first N unfiltered rows, with `total`
  set to N. So `total` and `results.length` match but the rows
  don't match the filter. Always sanity-check that filter
  applications survive to the returned rows — a curl that asserts
  every result matches the filter catches this in 30 seconds.
- **TypeScript rejects duplicate object-literal properties.** The
  trick `{ ok: true, ...payload, ok: true }` is a syntax error. Use
  trailing position instead: `{ ...payload, ok: true }`. The
  behaviour is identical (`ok: true` is the last assignment and
  always wins), and the trailing form is what TypeScript will
  accept.
- **Push the latest code in a coordinated way with any schema
  change.** Code on `main` may reference columns added by a future
  migration. If you push code first and migrate second, the API
  returns 500 (`column does not exist`) until the migration is
  applied. Apply schema changes as a single batch right after
  deploying, or hold the push until migrations are confirmed
  applied. See the [Migration strategy](#migration-strategy) below.
- **The `pkb-knowledge-base` skill is heavily project-specific.**
  When working on a small Vercel-deployed Supabase + Next.js +
  Gemini service, load that skill first — it has a wealth of
  project-specific gotchas (auto-commit remotes, Vercel email
  matching, GitHub PAT scopes) that this class-level skill doesn't
  repeat.
- **Don't cut a feature and add its replacement in the same
  commit.** The cut must be reversible independently. If the
  replacement breaks in production, you need to be able to revert
  the cut without losing the replacement work. Two separate
  commits, two separate reverts.
- **Don't remove response fields, empty them.** Clients commonly
  use `item.get("url") or ""` or `result.get("field")` patterns
  that handle empty-string defaults but break on missing keys.
  Removing a field is more invasive than setting it to `""`.
  The exception is when the field has security implications
  (e.g., leaking a backend token, exposing internal IDs) — then
  drop it deliberately and document the breakage.
- **Don't drop DB columns in the same commit as the code change
  that stops writing them.** Keep the column for one iteration
  as a rollback safety — "re-enable the env var, the column
  fills back up". The drop is a separate, later commit that
  comes after the cut has been observed working in production.
- **Don't `rm` local mirrors in the same change as removing the
  sync.** `git rm --cached <file>` keeps the file locally and
  in git history; it's the safe way to "freeze" a snapshot.
  True deletion loses the verification artifact that proves
  the migration worked.
- **Token rotation / account decommissioning are USER ACTIONS,
  not agent tasks.** A leaked PAT in `.git/config` is a problem
  the agent should flag and document, but the actual GitHub-side
  revocation must be done by the user (the agent doesn't have
  admin access to the upstream). List these explicitly in the
  plan, do NOT do them silently, and do NOT skip them. If the
  user says "I'll do it later", set a calendar reminder in
  memory so the next session follows up.
- **The "tier 1/2/3" optimization framework helps when there are
  many parallel issues.** Use it when a feature audit surfaces
  ≥5 issues across latency, correctness, security, and code
  complexity. The tiers are: T1 (fix now, blocks the feature's
  value), T2 (high-value but defers), T3 (long-term
  hardening). When the cut recommendation is accepted, the
  entire T1/T2/T3 list collapses — those issues no longer
  exist because the feature is gone.
- **Next.js 16 (App Router) silently excludes underscore-prefixed
  folders from routing.** `app/api/pkb/_admin/...` looks
  reasonable but is treated as a private folder and skipped at
  build time. The route does not exist; `next build` does not
  warn. Symptom: the new route is missing from the
  `Route (app)` table at the end of build output; calling it
  returns the Next 404 page, not your route's 404. Fix: rename
  to a non-underscore path. Verify with
  `rm -rf .next && npx next build 2>&1 | grep -E '^\s*[├└] ƒ /'`
  immediately after creating a new route.
- **Next.js 15+ dynamic route params are Promises.**
  `const { id } = params` (sync destructure) is now a type
  error. Use `const { id } = await params`. Same applies to
  `searchParams`. The training data often shows the pre-15
  sync form.
- **Auth wrappers typed as `Promise<NextResponse>` block
  streaming endpoints.** The Next 16 recommended pattern for
  streaming is `new Response(stream, { headers })` (plain
  `Response`, not `NextResponse.json`). If your `withAuth()`
  signature only accepts `NextResponse`, the route will fail
  to compile. Widen to
  `Promise<Response | NextResponse> | Response | NextResponse`.
  `NextResponse extends Response`, so all existing callers
  still satisfy; new streaming callers can use plain `Response`.
  See `references/nextjs-16-route-handlers.md` for the full
  pattern.

## Phased feature cut (when the audit says remove)

When the backup-strategy audit (or any feature audit) concludes
"remove X", the work is NOT a P0 fix. It is a separate workflow
with a different shape: **phased, contract-preserving, with a
safety net in place before the cut**. The P0/P1/P2 sweep
workflow above is for tightening an existing feature; this is
for taking one out. The two are often run in sequence — audit
first, then cut.

### Phase 0 — Consumer discovery (do not skip)

Before writing a single line of code, find every consumer of
the feature. This is what makes the plan concrete and what
prevents breaking downstream callers.

```bash
# 1. Find code that calls the API endpoints
rg -l 'service-name|/api/.*|x-api-secret|client-key' /opt/<other-svc>/

# 2. For each consumer, find the request payload + the response
#    fields they actually consume (not just the ones they could)
rg -n 'url|github_path|content_hash|item\.get' /opt/<other-svc>/handlers/

# 3. Check for any read path from the data store being removed
#    (e.g., a separate git clone of the GitHub repo, a scheduled
#    S3 pull, etc.)
rg -n 'github\.com/.*blob/main/notes' /opt/<other-svc>/
```

Build a **contract surface** doc listing for each endpoint:
request fields the consumer sends, response fields the
consumer reads. If a consumer reads `results[].url`, the `url`
field is load-bearing — it must stay in the response shape
even if the value becomes `""`.

User-phrase trigger: "注意 X 用到的接口不要挂" / "make sure
downstream consumers don't break". When you see this, the
discovery phase is mandatory. The consumer's test suite is
also the acceptance criteria for the cut — if their tests
still pass, the cut worked.

### Phase 1 — Safety net (must complete before Phase 4)

Implement the **replacement** mechanism first. If the audit
recommends "remove X, replace with Y", Y must be working and
round-trippable before X is cut.

- Build Y (e.g., periodic full export to R2/S3, a different
  service, a simpler in-house approach)
- Test round-trip: write → export → wipe → import → verify
- Wire the cron / trigger
- Run for at least one cycle on production data
- Only then proceed

This sequence is non-negotiable. If you cut X first and Y
breaks, you have no data. The audit's "remove X" recommendation
is conditional on Y existing; Y existing is verified by an
actual restore, not a code review.

### Phase 2 — Contract lock-in

Add tests that pin the consumer contract. The consumer should
not need to change code; the provider changes values, not
shapes.

- Add a fixture test asserting every response field the
  consumer reads is still present (even if `""`)
- Run the consumer's test suite against your local dev server
  to prove nothing breaks
- Document the contract in `docs/consumer-contract.md` (or
  in the audit's worked example) so future changes have a
  written spec to check

### Phase 3 — Decision gate (block here)

List the user decisions the cut requires. Do not proceed
until the user answers each one explicitly:

1. **What fills the void?** A field that was a GitHub URL is
   now empty — does the user want `""`, drop the field, or
   a new source? Each has different consumer impact.
2. **Replacement backend chosen?** R2 vs S3 vs B2 vs local —
   each has different cost / setup / egress / vendor-lock-in
   profiles.
3. **Upstream plan dependency?** Some replacements require
   Pro / paid tier (e.g., Supabase PITR); confirm the user
   is on the right plan.
4. **Out-of-band ops?** Token rotation, account
   decommissioning, Vercel env var removal, billing changes
   — these are user-action items, not agent tasks. List them
   so the user can do them; do NOT do them automatically and
   do NOT silently skip them.
5. **Rollback window?** How long does the consumer have to
   adapt if the cut introduces a behavior change? This sets
   the deadline for Phase 6 cleanup.

The user's answers go in the plan doc verbatim — they are
the spec for Phase 4.

### Phase 4 — Surgical cut

Now the code changes. Keep the diffs small and reversible:

- **Keep DB columns** the feature wrote to. Stop writing, keep
  reading (or vice versa). Drop them in a later phase so the
  rollback path is "re-enable one boolean", not "re-create
  table".
- **Empty, don't drop, response fields.** Clients commonly
  use `item.get("url") or ""` patterns. Removing a field is
  more invasive than setting it to `""`. The exception is
  when the field has security implications (e.g., leaking
  a backend token) — then drop it.
- **Don't combine "add replacement" + "cut feature" in one
  commit.** The two need to be revertable independently. If
  the replacement breaks in production, you need to be able
  to revert the cut without losing the replacement work.
- **Keep local mirrors in git** but mark them frozen
  (`git rm --cached` rather than `rm`). The history is
  useful for verifying the migration worked; true deletion
  loses the verification artifact.
- **One P0 per commit** as in the standard workflow. Don't
  combine "remove pushToGitHub" + "remove hardDelete GitHub
  cleanup" + "remove getOctokit" — three commits, three
  reverts.

### Phase 5 — End-to-end verify

Run the consumer's test suite against the cut version.
Specifically look for three categories:

- **Behavior change the consumer handles gracefully** (empty
  url → no link shown) — acceptable, document in commit
  message so the user knows what their end-users will see.
- **Behavior change the consumer breaks on** (missing field,
  changed type, status code change) — bug, revert or fix
  before declaring done.
- **Test fixtures that mock the old behavior** — these
  describe the pre-cut world. Either update consumer's
  mocks too (if the consumer is in scope) or accept that
  those tests now describe historical behavior and the
  consumer's owner must update them later.

### Phase 6 — Deferred cleanup (separate commit series)

In a later iteration, after the cut has been observed working
in production for ≥1 cycle:

- Drop DB columns (with a migration)
- Remove env vars from Vercel
- Update README's "Features" list to remove the cut feature
- Decommission the external service (GitHub repo, S3 bucket
  on the old plan, etc.)
- Remove the audit reference from the work doc

Do NOT bundle this with the cut itself. The cut is
reversible; the column drop is not. The observation window
catches the "we forgot about X" cases — they always exist.

## Migration strategy

When a P1/P2 feature requires a schema change, the codebase needs
**two files**, not one:

- `supabase/migration.sql` — the **canonical snapshot** for fresh
  deployments. Every schema change that ships to `main` gets
  incorporated here, so a new project clone can run a single
  file to get a working database.
- `supabase/migrations/YYYY_MM_DD_<feature>.sql` — the
  **incremental file** for existing deployments. One per feature.
  Idempotent (`IF NOT EXISTS`, no destructive changes) so re-runs
  are safe.

Rules:

1. **Both files stay in sync at `main`**. The snapshot is the
   union of every incremental file, in the same order. Diff
   discipline: a new column added to an incremental file is also
   added to `migration.sql` in the same commit.
2. **Each incremental file is runnable on its own**. No
   "this depends on migration N from last week" — the SQL
   includes every column it needs, with `IF NOT EXISTS` guards
   for backfill safety.
3. **Backfills are inline** in the incremental file using
   `UPDATE ... WHERE col IS NULL` so re-runs skip already-filled
   rows. This makes the migration safe to apply multiple times.
4. **Document the deploy coupling in the README**: which code
   feature requires which migration file, so a fresh reviewer can
   apply them in order.
5. **Hold the push** if the migration can't be run before the
   code deploys. Two commits — one for migration, one for code —
   beats a 5-minute window of 500s.

## Pattern: background work with `after()`

When the user-facing response shouldn't block on a slow side effect
(Gemini embedding, email send, large GitHub push), use Next.js
`after()` to schedule the work past the response:

```typescript
import { after } from 'next/server'

export const POST = withAuth(async (req) => {
  // Fast path: validate, insert row, return 200
  const { note } = await saveNote(...)
  await getSupabase()
    .from('notes')
    .update({ embedding_status: 'pending' })
    .eq('id', note.id)

  // Slow path: schedule after the response is sent
  after(async () => {
    try {
      const embedding = await embedText(note.content, 'RETRIEVAL_DOCUMENT')
      await getSupabase()
        .from('note_embeddings')
        .upsert({ note_id: note.id, chunk_text: note.content, embedding },
                 { onConflict: 'note_id' })
      await getSupabase()
        .from('notes')
        .update({ embedding_status: 'done' })
        .eq('id', note.id)
    } catch (err) {
      await getSupabase()
        .from('notes')
        .update({ embedding_status: 'failed' })
        .eq('id', note.id)
    }
  })

  return ok({ id: note.id })  // ~200ms vs ~1500ms with inline embed
})
```

Caveats:

- **Status column required**. The search path must filter by
  `status = 'done'` or notes will appear before their embedding
  is ready, then disappear when the background work fails.
- **Background work can be killed** by the host after the response.
  The row stays at `pending`; provide an admin endpoint
  (`POST /api/pkb/embed-pending`) and wire it to a cron for
  self-healing.
- **`after()` is for Edge and Node runtimes in Next 13.4+**. On
  older versions or other frameworks, fall back to fire-and-forget
  promises and accept the at-most-once guarantee.

## Pattern: idempotent save via content hash

For any "save" endpoint that the user might trigger with the
same input twice (a chat agent re-sending a message, a UI
double-submit), enforce idempotency at the schema level:

```sql
ALTER TABLE notes ADD COLUMN content_hash TEXT;
CREATE UNIQUE INDEX notes_content_hash_unique
  ON notes(content_hash) WHERE content_hash IS NOT NULL;
```

```typescript
import { createHash } from 'node:crypto'

export function computeContentHash(content: string): string {
  const normalized = content.trim().replace(/\s+/g, ' ')
  return createHash('sha256').update(normalized, 'utf8').digest('hex')
}
```

Race-loser handling: two concurrent saves with the same content
can both pass the existence check. The unique index causes one
insert to fail with Postgres error 23505. Catch it and re-read
the winner:

```typescript
if (error.code === '23505') {
  const winner = await findNoteByHash(hash)
  if (winner) return { note: winner, idempotent: true }
}
```

The TS normalization (trim + collapse whitespace) MUST match the
SQL backfill formula exactly. Test the canonical SHA-256 of a
known input against an external calculator to verify.

## Pattern: response envelope (`ok` / `fail`)

Use two helpers, never write `NextResponse.json({...}, {...})`
inline. This keeps the API contract enforced at the type level:

```typescript
// lib/responses.ts
export function ok<T extends Record<string, unknown>>(payload: T, init?: ResponseInit) {
  // `ok: true` MUST be the LAST assignment so a caller passing
  // {ok: 'overridden'} can't break the success contract.
  return NextResponse.json({ ...payload, ok: true }, init)
}

export function fail(error: string, status: number, detail?: string) {
  const body: Record<string, unknown> = { error }
  if (detail !== undefined && detail !== null && detail !== '') {
    body.detail = detail
  }
  return NextResponse.json(body, { status })
}
```

In every route:

```typescript
import { fail, ok } from '@/lib/responses'
// ...
return ok({ id, type, topics, created_at: ..., url, idempotent: false })
// or
return fail('Unauthorized', 401)
```

Backwards compat when adding `ok: true` to an existing endpoint
that didn't have it: the field is additive. Old clients ignore
unknown fields; new clients key off `ok` for routing success vs
error. The one route that didn't have `ok: true` (typically
search) gains it; the response shape is otherwise unchanged.

## Pattern: vitest setup for Next.js + TS

```json
// package.json
"scripts": {
  "test": "vitest run",
  "test:watch": "vitest"
},
"devDependencies": {
  "vitest": "^2"
}
```

```ts
// vitest.config.ts
import { defineConfig } from 'vitest/config'
import path from 'node:path'

export default defineConfig({
  resolve: { alias: { '@': path.resolve(__dirname, '.') } },
  test: { environment: 'node', include: ['tests/**/*.test.ts'] },
})
```

```ts
// tests/lib/notes.test.ts
import { describe, it, expect } from 'vitest'
import { computeContentHash, inferNoteType } from '@/lib/notes'

describe('inferNoteType', () => {
  it('detects code: markdown code blocks', () => {
    expect(inferNoteType('```js\nconst x = 1\n```')).toBe('code')
  })
  // ...
})
```

Pure functions are easy. Functions that take `NextRequest` need
a tiny mock:

```ts
function makeReq(headers: Record<string, string> = {}): NextRequest {
  return { headers: { get: (n: string) => headers[n.toLowerCase()] ?? null } }
    as unknown as NextRequest
}
```

Functions that hit Supabase / Octokit / Gemini are harder. Two
options:

- **Don't test them.** Cover the pure functions (parsing,
  inference, response shapes, middleware) and verify the
  I/O-bound code with curl against the deployed service.
- **Mock with `vi.mock`**. The mocking is verbose and brittle;
  the curl test is faster to write and proves the same thing.

For most APIs, "test the pure functions + curl-verify the I/O" is
the right trade. Skip the I/O mocks unless the function has
non-trivial branching on the response.

## Pattern: streaming response with `ReadableStream` (Next 16)

For endpoints that return a multi-MB payload (downloads, exports,
logs), the Next 16 doc shows this pattern (from
`node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/route.md`):

```ts
import { withAuth } from '@/lib/auth'
import { streamJsonlDump } from '@/lib/backup'

export const GET = withAuth(async (req) => {
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const encoder = new TextEncoder()
      try {
        for await (const chunk of streamJsonlDump()) {
          controller.enqueue(encoder.encode(chunk))
        }
        controller.close()
      } catch (err) {
        // Once the response has started, status is locked. Emit a
        // structured error line the consumer can grep for.
        controller.enqueue(encoder.encode(
          JSON.stringify({ _kind: 'error', message: String(err) }) + '\n'
        ))
        controller.close()
      }
    },
  })

  return new Response(stream, {
    status: 200,
    headers: {
      'Content-Type': 'application/x-ndjson; charset=utf-8',
      'Content-Disposition': `attachment; filename="dump-${date()}.jsonl"`,
      'Cache-Control': 'no-store',
    },
  })
})
```

The `for await (const chunk of asyncGenerator)` is the canonical
Web Streams adapter. Pair with a JSONL producer (manifest line +
content lines) for a "stream a large DB dump to a download"
pattern. The full worked example with a Supabase cursor-paginated
iterator and restore script is in
`references/streaming-backup-pattern.md`.

## See also

- `references/curl-verification-matrix.md` — bash/Python template
  with example matrices for common refactor types
- `references/backup-strategy-audit.md` — the dual-write / backup
  audit framework, with a worked example (PKB: GitHub mirror removed)
- `references/nextjs-16-route-handlers.md` — Next 16 App Router
  specifics: private folders, async params, streaming + auth typing
- `references/streaming-backup-pattern.md` — JSONL dump format
  (manifest + cursor pagination + footer), Cloudflare R2 default,
  restore script
- `codegraph` skill — for the initial P0/P1/P2 issue-list drafting
- `pkb-knowledge-base` (project skill) — for concrete examples
  of every pattern in this skill, applied to a real Vercel +
  Supabase + Next.js service
