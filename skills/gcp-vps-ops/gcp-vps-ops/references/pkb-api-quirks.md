># PKB API Quirks

## Write vs Search Field Asymmetry

Write returns: `{ok, id, type, topics, created_at, url}`
Search returns: `{title, content, type, topics, created_at}` — **no id, no url**

This means you cannot get a note's `id` or `url` back after writing it, and you cannot use `id` to reference/update/delete a note via the API.

## Topics Pollution

When writing `topics: ["ABC", "DEF"]`, searching may return `topics: ["topics", "ABC"]`. The search index tokenizes the full content including the word "topics" itself. This is a server-side behavior, not a client bug.

## No DELETE/PUT

- `DELETE /api/pkb` → HTML (Next.js 404 page)
- `PUT /api/pkb` → HTML
- `PATCH /api/pkb` → HTML
- Only `POST /api/pkb` (write) and `POST /api/pkb/search` (search) and `GET /api/pkb/health` work

To delete notes: use GitHub repo `caozuohua/pkb` → `notes/` directory.
**Note**: as of 2026-06-12 the GitHub mirror is cut. New writes
return `url: ""` (empty string, never null). See "Note URL Format" below.

## Search Requires Real Keywords

Search with empty string or whitespace returns 0 results. Must provide a real keyword. To enumerate all notes, iterate through common keywords and dedupe results client-side.

## Deduplication Strategy

Search results overlap heavily across queries. Dedupe by `content[:80]` prefix in local code.

## Auth Pattern

Header: `x-api-secret: <value>` (not `Authorization: Bearer`)

## Note URL Format (POST-GITHUB-MIRROR-CUT, 2026-06-12)

**`url` is always `""` (empty string) in the response**, never a
GitHub URL. Pre-2026-06-12 the API returned URLs like
`https://github.com/caozuohua/pkb/blob/main/notes/{date}-{ts}.md`
pointing to the GitHub mirror; that mirror is now disabled.

Client behavior:
- luck-agent's `_normalize_pkb_result_item` does
  `str(item.get("url") or "")` — safe with `""` (returns `""`)
- luck-agent's `format_pkb_result_items` does `if url:` to decide
  whether to show a link — `if "":` is falsy, so the link is just
  not rendered. **No luck-agent changes needed** when url="".
- Custom callers that do `item["url"]` without `or ""` will
  raise `KeyError` for the search path (search never returned url
  anyway) or get `""` (write path).

The 15-test `tests/contract/luck-agent.test.ts` suite locks this
invariant — it would fail if url ever became `null` or `undefined`.

## Migration-time check: 404 on /api/pkb/admin/backup is a build lag, not a bug

Vercel auto-deploys from GitHub. If your local commits are ahead of
origin (`git status` shows "Your branch is ahead of origin/main by N"),
Vercel is still serving the pre-cut build. The pre-cut build does
NOT have `/api/pkb/admin/backup` or `/api/pkb/admin/export` — both
return 404 (Next.js HTML page).

**Verify your local commit was deployed** by checking the
`url: ""` invariant in a recent write response. If you still get
GitHub URLs back, the new code is not deployed yet — push or wait
for Vercel build.

## Old behavior — git auto-commit trap (historical, no longer applies)

**Pre-2026-06-12 ONLY**: Vercel auto-committed every `saveNote` to
the GitHub mirror. If you ever re-introduce GitHub-backed storage,
re-read `references/git-auto-commit-2026-06-12.md` for the recovery
procedure (the `git reset --hard origin/main` rule still applies
to any auto-commit remote).
