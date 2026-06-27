---
name: rag-ingestion-pipeline
description: "Use when building or refactoring a personal knowledge base / RAG corpus on GCP (Google Drive → parsers → chunker → Vertex AI Embedding → PostgreSQL+pgvector) intended to be migrated to Supabase free tier after GCP credit expiry. Covers the MIME_HANDLERS dispatch + extract(bytes) parser interface, legacy vertexai.generative_models SDK, STT v2 BatchRecognize for video, GCS temp-then-cleanup pattern, and idempotent upserts via drive_file_id UNIQUE. Triggers: 'build a personal KB', 'RAG corpus from Drive', 'Drive → vector pipeline', 'pgvector ingestion', 'refactor the ingest layer', 'luck-agent RAG backend'."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [rag, ingestion, drive, vertex-ai, pgvector, gcp, knowledge-base, stt-v2]
    related_skills: [plan, pkb-knowledge-base, simplify-code, requesting-code-review]
---

# RAG Ingestion Pipeline (GCP → Supabase migration-ready)

## Overview

The user maintains a personal knowledge base project at `~/knowledge_base/`
that is **explicitly designed** as the RAG backend for `luck-agent`. The
end state is a PostgreSQL+pgvector corpus that survives the GCP credit
window: build everything on Vertex AI during the credit phase, then
`pg_dump` → restore to Supabase free tier **without re-embedding** (the
embedding model is identical on both tiers).

The architecture is rigidly defined. Future sessions that touch this
project — whether scaffolding, refactoring, or adding a new MIME handler
— must follow the same patterns or the migration safety net breaks.

This skill is the class-level umbrella. The concrete instance lives at
`/home/caozuohua99/knowledge_base/`. The reference implementation there
is the canonical example; new sessions should `tree` it before
diverging.

## When to Use

- User asks to initialize or scaffold `knowledge-base/`
- User asks to refactor an existing ingest layer to a cleaner architecture
- User wants to add a new MIME handler (e.g. .epub, .rtf, audio)
- User asks to migrate from GCP to Supabase
- User reports a bug in any `ingest/*` module and you need to fix it without breaking the contract

**Do NOT use for:** the existing `/opt/pkb/` Next.js+Supabase personal
knowledge base — that's a different stack (Next.js + Supabase + Gemini
JSONL backup) covered by `pkb-knowledge-base`.

## Architecture (one-pager)

```
Google Drive (top-level folders → domain partition)
        │
        ▼ drive_reader.iter_drive_files()
        │   OAuth + recursive walk + Google-native format EXPORT
        │   (Docs → text/plain, Sheets → xlsx, Slides → pptx)
        ▼ dispatcher.extract_text(raw, mime, name, file_id)
        │   MIME_HANDLERS dict → pdf/docx/pptx/xlsx/gdoc/text/image/video
        │   Each parser exposes `extract(bytes) -> str`
        ▼ chunker.split_chunks(text, settings)
        │   Paragraph-first, tiktoken cl100k, 512 target / 64 overlap
        ▼ embedder.embed_chunks(chunks, settings)
        │   Vertex AI TextEmbeddingModel, batch 250
        │   Model: text-multilingual-embedding-002 @ 768d (LOCKED)
        ▼ db.store.upsert_document_with_chunks(...)
        │   documents(drive_file_id UNIQUE) + chunks(ON DELETE CASCADE)
        ▼ PostgreSQL + pgvector
```

Hybrid search: `retrieval/search.py` runs vector cosine + tsvector
fulltext in parallel, fuses with RRF (K=60, 5× oversample).

## Key Design Decisions (the contract — do not break)

| Decision | Why |
|---|---|
| `text-multilingual-embedding-002` @ 768d | Same model on Vertex AI and Supabase tier → zero re-embed on migration |
| `MIME_HANDLERS` dict with value = `doc_type` | Single source of truth for both routing and the `documents.doc_type` column |
| `extract(raw_bytes) -> str` on every parser | Uniform interface; adding a MIME = one entry in HANDLERS + one branch |
| `extract_text(raw, mime, name, file_id)` dispatcher | `name`/`id` flow through to GCS blob names and error logs |
| `split_chunks(text, settings)` chunker | Pure function; no I/O; testable without DB |
| `ingest/pipeline.py` is a separate orchestrator | CLI (`run.py`) is a thin wrapper; pipeline is library-callable |
| Legacy `vertexai.generative_models.GenerativeModel` | User's chosen SDK; NOT `google-genai`. Lazy `_model` global |
| Legacy `vertexai.language_models.TextEmbeddingModel` | Matches the rest of the stack; no `google-genai` import |
| STT v2 `BatchRecognizeRequest` (NOT `RecognizeRequest`) | True async server-side; `recognizers/_` default works for personal use |
| GCS cleanup in `finally` (not just success) | A 150MB failed blob is a cost + a leak |
| Drive exports Docs as `text/plain` | Dispatcher `gdoc` branch is `decode("utf-8")`; PDF export breaks the chain |
| `drive_file_id UNIQUE` + `chunks(doc_id, chunk_index) UNIQUE` | Idempotent resume; safe to re-run pipeline any time |
| Store.upsert: DELETE then INSERT in one tx | Atomic replace; ON DELETE CASCADE wipes old chunks |
| ivfflat `lists=100` + `SET LOCAL ivfflat.probes=10` per session | Sensible defaults for 0→100k chunk corpus |
| Excel: 100-row truncation per sheet | Bounds the Gemini call; matches user's reference design |
| RRF K=60 with 5× oversample | Cormack et al. 2009 default; no per-query tuning needed |

## Per-component contracts

### `config.py` — env-driven, dual access

Two access patterns, both must work:

```python
# Legacy: parsers use module-level constants (vertexai.init needs them)
from config import GCP_PROJECT_ID, GCS_TEMP_BUCKET

# Modern: pipeline / run use the typed Settings
from config import get_settings
```

`load_dotenv()` runs at import time so the legacy constants see real values.
Shell env vars win (`override=False`).

Required fields: `GCP_PROJECT_ID`, `GCS_TEMP_BUCKET`, `DATABASE_URL`,
`DRIVE_FOLDER_MAP_JSON`, `DRIVE_OAUTH_CLIENT_SECRETS`. `LARGE_FILE_THRESHOLD_MB=50`
is informational (no streaming path implemented yet — flag if asked).

### `ingest/<parser>.py` — uniform interface

Every parser exposes one public function: `extract(raw_bytes) -> str`.
Module-level state (lazy `_model` global for Gemini) is OK; never block
import on it. Wrap AI calls in `tenacity` retry (3 attempts, exponential).

### `ingest/dispatcher.py` — the routing table

```python
MIME_HANDLERS: Final[dict[str, str]] = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xlsx",
    "text/plain": "gdoc",  # see pitfall #1
    "image/jpeg": "image", "image/png": "image",
    "image/gif":  "image", "image/webp": "image",
    "video/mp4":  "video", "video/quicktime": "video",
    "video/x-msvideo": "video", "video/webm": "video",
    "text/markdown": "text", "text/csv": "text",
}

def extract_text(raw_bytes, mime_type, filename="", file_id="") -> str: ...
def doc_type_for(mime) -> str: ...  # raises on unknown
```

To add a new format: one new entry in `MIME_HANDLERS` + one new branch
in `extract_text` + a new `ingest/<new>_parser.py` module.

### `ingest/drive_reader.py` — export MIMEs matter

```python
_EXPORT_MIME = {
    "application/vnd.google-apps.document": "text/plain",  # NOT pdf
    "application/vnd.google-apps.spreadsheet": "...spreadsheetml.sheet",
    "application/vnd.google-apps.presentation": "...presentationml.presentation",
}
```

`text/plain` is intentional. If you change it to `application/pdf`,
the dispatcher's `gdoc` branch (`decode("utf-8")`) will see PDF bytes
and silently produce garbage. (See pitfall #1.)

### `ingest/chunker.py` — paragraph-first, tiktoken

`split_chunks(text, settings) -> list[Chunk]`. Strategy:
1. Split on blank lines into paragraphs.
2. Greedy-pack paragraphs into ~512-token windows with 64-token overlap.
3. Any window still over target → sentence-split → re-pack.

### `ingest/embedder.py` — batched, identical model on both tiers

`embed_chunks(chunks, settings) -> list[list[float]]` and
`embed_query(query, settings) -> list[float]`. Vertex AI batch limit is
250. `task_type` is NOT honored by the legacy SDK; accept the recall
delta and stay consistent with the rest of the layer.

### `ingest/pipeline.py` — single public entry

`run_ingest(*, domain=None, reingest=False, progress_cb=None) -> dict[str, int]`.
Per-file failures are logged and skipped; the pipeline never aborts on
one bad file. Returns `{ok, skipped, failed, total}`.

### `db/store.py` — write-side only

Read paths live in `retrieval/`. `Store` wraps a psycopg3 connection pool.
`upsert_document_with_chunks(...)` does DELETE → INSERT in one tx.

### `retrieval/search.py` — RRF fusion

Run vector and fulltext queries in one tx, build rank maps keyed by
`chunk_id`, score = sum(1/(K+rank)). Return top-K hits.

## Common Pitfalls

1. **Drive `gdoc` export must be `text/plain`.** The dispatcher's `gdoc`
   branch is `raw_bytes.decode("utf-8", errors="ignore")`. If you
   `drive_reader` exports Docs as `application/pdf` (the natural-looking
   choice), the dispatcher will decode PDF bytes as UTF-8 and produce
   garbage. Keep the export mime aligned with the dispatcher's branch.

2. **Don't hardcode `image/jpeg` in OCR.** Sniff from magic bytes
   (`b"\x89PNG"`, `b"\xff\xd8\xff"`, etc.). PNG/GIF/WebP are real inputs.

3. **GCS cleanup MUST be in `finally`.** A failed STT call still
   leaves a 150MB blob in your bucket. Wrap upload → recognize →
   delete in try/finally; the delete branch is best-effort (never raises).

4. **Truncate Excel before Gemini, not after.** Sheets over 100 rows
   exceed Flash's comfortable context. Truncate to 100 lines + a
   `[...共N行，已截断]` marker; Gemini then summarises what it can see.

5. **ivfflat needs `SET LOCAL ivfflat.probes = 10` per session.**
   Without it, default probes (~1) gives terrible recall. Do this in
   the same transaction as the vector query.

6. **Don't mix `google-genai` and `vertexai` SDKs in the same project.**
   They both work but make dep auditing painful. The user picked
   legacy `vertexai`; honor it. If you must use `google-genai` for
   some specific feature, isolate it and add a comment explaining why.

7. **`embed_query` loses `task_type` hint on legacy SDK.** The legacy
   `TextEmbeddingModel.get_embeddings()` does not surface `task_type`.
   Accept slightly worse recall for queries; don't switch SDKs to fix it.

8. **`gdoc` vs `text` doc_type looks redundant.** Both decode UTF-8,
   but `gdoc` is "came from Google Docs export" and `text` is "user
   uploaded a .md or .csv". Future filtering (e.g. "show me only my
   Drive notes") may want to distinguish them. Don't collapse.

9. **`Store.upsert` is a DELETE+INSERT, not an UPDATE.** It looks
   like overkill but it cleanly handles the case where the new file
   has fewer chunks than the old one (CASCADE on chunks). Don't
   "optimize" it to a real UPDATE.

10. **The `extract_text` dispatcher logs `mime + filename + file_id` on
    failure then re-raises.** Pipeline catches the re-raise and counts
    it as `failed`. Don't swallow the exception inside dispatcher.

11. **Config `load_dotenv` runs at import time.** If you import
    `config` before `load_dotenv` would have a chance to run, the
    legacy module-level constants will be empty. `config.py` does
    this itself; don't re-order imports.

12. **`text/multilingual-embedding-002` is end-of-lifing.** Check
    Vertex AI model catalog before any 6+ month project break; if the
    model is being deprecated, plan a re-embed well before the
    Supabase migration window.

## Migration to Supabase (already designed, do not re-invent)

```bash
pg_dump --no-owner --schema-only "$GCP_DATABASE_URL" > schema.dump
pg_dump --data-only --no-owner "$GCP_DATABASE_URL" > data.dump
psql "$SUPABASE_DATABASE_URL" -f schema.dump
psql "$SUPABASE_DATABASE_URL" -f data.dump
# Switch DATABASE_URL in .env. Re-run `kb search` to verify.
# Embeddings do NOT need to be regenerated — same model.
```

## Verification Recipe

After any change to the ingest layer, run all four:

1. **Compile**: `python3 -m compileall -q ingest db retrieval config.py run.py`
2. **Import**: load every module — any circular import or syntax error
   shows up here. Use `uv run python3 -c "import ingest, db, retrieval, run"`.
3. **CLI**: `uv run python3 run.py --help` and per-subcommand `--help`.
4. **Smoke** (no network): see `scripts/smoke_test.py` — calls
   `extract_text` for every text-only MIME, calls `split_chunks` with
   a small token override, and walks the full `MIME_HANDLERS` table.

If any step fails, fix the contract before touching the docs.

## One-Shot Recipes

### Add a new MIME handler (e.g. .epub)

1. Add `application/epub+zip: "epub"` to `MIME_HANDLERS`.
2. Add `if handler == "epub": return epub_parser.extract(raw_bytes)` branch
   in `extract_text`.
3. Create `ingest/epub_parser.py` with `extract(raw_bytes) -> str` (use
   `ebooklib`, or strip HTML and return).
4. Run the verification recipe.

### Tune embedding dim for a one-off experiment

Don't change `EMBEDDING_DIM` in `.env` — that breaks the migration
contract. Instead, fork a side-corpus at the new dim and keep the
main pipeline at 768.

### Re-ingest one bad file

```bash
uv run python3 run.py reindex --drive-file-id <ID>
```

This drops the old document (CASCADE wipes chunks) and re-runs the
full pipeline for that one file.
