---
name: static-data-scaffold
description: "Scaffold a data-driven static site (HTML + JSON) for GitHub Pages with search, filters, tags, and detail modals. Use when user wants a zero-build static site backed by a JSON data source that's portable across platforms."
---

# Static Data Scaffold

## Overview

Scaffold a pure static HTML/CSS/JS site with a JSON data source as single source of truth. Zero build step, deploys to GitHub Pages, fully portable data.

**When to use:** User wants a case study library, portfolio, knowledge base, showcase, or any content-driven site that must be:
- Hosted on GitHub Pages (free, no server)
- Portable (data can migrate to any platform later)
- Maintainable by non-developers (just edit JSON)
- Long-running with checkpoint/resume support

## Architecture

```
project/
├── data/
│   └── cases.json          # Single source of truth
├── css/
│   └── style.css           # Responsive design
├── js/
│   └── app.js              # Search, filter, render, modal
├── .github/
│   └── workflows/
│       └── deploy.yml      # Auto-deploy to Pages
├── index.html
├── .gitignore
└── README.md
```

**Key principle:** JSON is the ONLY data source. No external DB, no build step, no framework. The site is a thin client over a data file.

## Project Startup Checklist (Checkpoint/Resume)

Always start multi-phase static data projects with this sequence:

1. **Create local directory + `git init`**
2. **Create GitHub repo + push initial empty README** — establishes the checkpoint baseline
3. **Build skeleton** (HTML + CSS + JS + seed data) — first real checkpoint
4. **Iterate on features** (search, filters, tags, modal) — each is a commit
5. **Fill data** — can resume anytime by editing JSON

**Why:** User explicitly requires long-running projects to be checkpoint-resumable. Git commits at every meaningful milestone = ability to resume from any point.

## Data Schema Design

### Core fields (adapt to domain)

| Field | Type | Purpose |
|-------|------|---------|
| id | string | Unique identifier (e.g. `cn-huanneng-001`) |
| title | string | Item name |
| country | string | For geographic filtering |
| company | string | Organization |
| year | number | For temporal filtering |
| tech | string[] | Technology tags |
| scale | string | Size/category (large/medium/small) |
| investment | string | Budget range |
| roi | string | Outcome/ROI summary |
| summary | string | 2-3 sentence abstract |
| detail | string | Full description (detail page) |
| source | string | URL to original source |
| tags | string[] | Flexible multi-purpose labels |

### Tag system (flexible, not preset)

Tags are free-form. Suggested dimensions:
- **Energy type:** 火电/水电/核电/风电/光伏/储能/电网
- **Technology:** 数字孪生/IoT/AI/大数据/5G/区块链
- **Application:** 智慧电厂/智能电网/新能源运维/碳排放
- **Scale:** 大型/中型/小型

**Don't hardcode tag categories** — let users add tags freely. The tag cloud auto-generates from data.

## Implementation Steps

### Step 1: Skeleton

- Create directory structure
- Write `index.html` with semantic structure
- Write `css/style.css` (responsive, clean)
- Write `js/app.js` (load JSON, render cards, bind events)
- Write `data/cases.json` with 5-10 seed entries
- Write `.github/workflows/deploy.yml`
- Write `README.md`

### Step 2: Search & Filter

- Full-text search across all string fields
- Dropdown filters for: country, scale, year
- Tag cloud (sorted by frequency, click to filter)
- "Reset all" button
- Live count display ("Showing X / Y")

### Step 3: Detail Modal

- Click card → open modal with full details
- Meta grid (scale, investment, ROI, tech)
- Full detail text
- Source link
- Close via X button, overlay click, or Escape key

### Step 4: Data Population

- Add entries to `data/cases.json`
- Validate JSON format
- Commit after each batch

## GitHub Actions Deploy

```yaml
name: Deploy to GitHub Pages
on:
  push:
    branches: [main]
  workflow_dispatch:
permissions:
  contents: read
  pages: write
  id-token: write
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v3
        with: { path: . }
      - id: deployment
        uses: actions/deploy-pages@v4
```

## Data Quality & Reliability (User Priority)

User explicitly requires **information reliability confidence assessment** as a core requirement, not an afterthought.

### Confidence tagging

Every case MUST carry a `confidence` field:

| Level | Meaning | Criteria |
|-------|---------|----------|
| 高 | High | Official company report, press release, or government document |
| 中 | Medium | News article, industry publication, or trade show presentation |
| 低 | Low | Industry report mention, forum discussion, unverified source |
| 未标注 | N/A | No source available yet |

### Source quality rules

- **Always include `source` URL** — every claim must be traceable
- **Prefer primary sources** (company press releases, government filings) over secondary (news aggregators)
- **No source = low confidence** — if a case has no verifiable source, mark it low or exclude
- **Update confidence when better sources emerge** — it's not a one-time judgment

### Data quality workflow

When populating data in batches:
1. Collect cases into a batch file (`data/cases_batchN.json`)
2. Validate format (`python3 scripts/validate.py validate`)
3. Merge into main file, deduplicate by `id`
4. Re-validate merged file
5. Commit with descriptive message

### Reliability display in UI

- Show confidence badge on each card (color-coded: green=高, yellow=中, red=低, gray=未标注)
- Add confidence filter dropdown
- Show confidence level in detail modal

## Automated Data Update Pipeline

For long-running datasets, automate discovery and ingestion with a cron → subagent → validate → PR pipeline.

### Architecture

```
cronjob (weekly) → subagent searches news → writes candidates.json
  → GitHub Actions validates → creates PR → human reviews → merge
```

### Components

**1. Cronjob (Hermes scheduler)**
- Triggers weekly (e.g., Monday 09:00 local time)
- Spawns subagent with search task prompt
- Subagent uses `web_search` to find industry news, extracts structured candidates
- Output: `data/candidates.json`

**2. GitHub Actions Workflow** (`.github/workflows/weekly-update.yml`)
- Triggers on schedule OR `workflow_dispatch`
- Runs validation script on existing data
- If candidates exist: validates them, creates PR with review checklist
- Uploads report as artifact

**3. Validation script** (`scripts/cases_automation.py`)
- `--validate`: check existing data quality
- `--report`: generate update report
- `--full`: validate + report + export CSV/JSONL

**4. Human review gate**
- PR includes checklist: source reliability, no duplicates, field completeness
- Reviewer merges only after verification

### Subagent Prompt Template

```
You are a data update subagent for [DOMAIN] case studies.

Task: Search past week for [DOMAIN] news, extract candidate cases.

Steps:
1. web_search for [KEYWORDS] — take top 5 results per keyword
2. Extract structured cases with fields: [SCHEMA]
3. Read existing data/cases.json to avoid duplicates
4. Write candidates to data/candidates.json
5. Run: python3 scripts/cases_automation.py --validate
6. Run: python3 scripts/cases_automation.py --report
7. Output summary: new candidates, valid/invalid/duplicate counts

Rules:
- Only output verifiable cases with real source URLs
- Never fabricate data
- Mark confidence: 高=official source, 中=news, 低=industry mention
- If no new cases found, report "no new candidates this week"
```

### When to Use Automation

- Dataset needs regular updates from news/public sources
- User wants hands-off discovery with human review gate
- Project runs for months/years with ongoing data collection

## Deduplication (Critical for Multi-Agent / Repeated Ingestion)

When multiple agents or sessions contribute to the same dataset, dedup becomes essential. The `scripts/dedup.py` tool provides three-level detection:

1. **ID exact match** — same `id` field in existing data
2. **Title near-identical** — SequenceMatcher similarity >= 95%
3. **Title highly similar + company/year match** — similarity >= 90% AND same `company` AND same `year`

### Ingestion dedup workflow

1. Collect new cases into a batch file (`data/cases_batchN.json`)
2. Run `python3 scripts/dedup.py --check data/cases_batchN.json`
3. Use the `_clean.json` output (duplicates already filtered)
4. Merge clean cases into main `data/cases.json`
5. Run `python3 scripts/dedup.py` internal check to confirm

### Why this matters

Without dedup, parallel agents will repeatedly contribute the same cases (especially popular ones like major grid digitalization projects). The dedup engine uses fuzzy title matching to catch near-identical entries that differ only in minor wording. This caught 9 duplicates in a recent 44-case batch — a 20% waste rate.

Avoid false positives: the engine intentionally does NOT flag cases from the same company if titles differ substantially (e.g., "风电智慧运维" vs "光伏智慧运维" are different projects).

### Pitfalls

1. **Subagent timeout** — web search subagents can hit 600s timeout. Design prompts to be focused (specific keywords, limited scope). If timeout occurs, run the search yourself and write candidates directly.
2. **Low-quality candidates from web search** — subagents may extract plausible but unverified claims. The validation step catches these, but don't auto-merge without human review.
3. **Cronjob drift** — if search keywords become stale, update them quarterly based on trending topics in the domain.
4. **PR fatigue** — if weekly updates produce few candidates, consider biweekly or monthly cadence instead.
5. **Year misattribution (CRITICAL — user caught this)** — when collecting recent cases, subagents write year: 2026 for cases that are still 2025 plans/announcements. Hard rule: only mark a case as year N if you have evidence of the project being operational/commissioned/released in year N. A 2025 announcement of a 2026 plan stays year 2025. When in doubt, keep the earlier year. After writing a batch, explicitly audit: For each case marked 2026, what is the evidence it was actually operational/commissioned/released in 2026? Remove or downgrade cases that cannot be verified. **Reality check:** In a real 2025→2026 dataset collection session, zero cases were found for 2026 in most countries because subagents were backdating 2025 plans to 2026. Only China and the US had genuine 2026 operational/commissioned projects. If you cannot find a single verifiable year-N case for a country, that is normal — do not fabricate.
6. **Same-company series collapse** — when one group company (e.g. 国家电投) releases a batch of related sub-scenarios (carbon management / safety / hydrogen / smart mine) with a shared naming pattern, these are ONE program, not N independent cases. Deduplicate at the series level: if multiple candidates share company + year + a common naming pattern, collapse into a single entry with combined tags. **Real example:** A subagent produced 12 cases all named "国家电投AI大模型XX应用2026" (carbon/safety/hydrogen/smart mine/wind/solar/storage/etc). These should be ONE entry tagged with all sub-domains, not 12 separate entries. Rule of thumb: if >3 cases from the same company in the same year share a naming template, they are sub-scenarios of one program.
7. **Language inconsistency in enum fields** — subagents sometimes write English values (large, AI) where the existing data uses Chinese (大型, 人工智能). Always normalize enum fields during validation. Add a post-merge cleanup pass that maps known variants to canonical values. Check: scale, country, tech tags, confidence level.
8. **Data scarcity honesty** — when a country has genuinely few verifiable projects (e.g. Iraq power digitalization in 2025-2026), do not pad with low-quality entries. It is better to have 0 cases for a country than 3 cases with confidence=low and no verifiable source. Mark the gap in a TODO file and move on.

## Data Portability

The JSON data source can be exported to:
- **CSV** — `python3 -c "import json,csv; data=json.load(open('data/cases.json')); ..."`
- **SQLite** — load JSON into a table with flexible schema
- **Supabase/Notion** — import via API
- **Any future platform** — JSON is universally understood

## User Preferencesences

- User prefers 简体中文 output
- User prefers checkpoint/resume patterns for long-running projects
- User prefers lightweight, zero-build solutions over heavy frameworks
- User prefers data portability over platform lock-in
- User prefers "先 MVP 再扩展" — ship a working skeleton fast, then iterate on data and features
- User prefers information reliability as a first-class concern, not an afterthought
- User prefers batch data collection with confidence tagging and source traceability

## Linked Files

- `templates/index.html` — Starter HTML template (replace `{{TITLE}}`, `{{HEADER_TITLE}}` placeholders)
- `references/data-schema.md` — Full data schema reference, validation rules, migration paths, tag taxonomy
- `references/power-digital-cases.md` — Real-world project reference: power-digital-cases dataset (235 cases, 39 countries)
- `references/batch-data-workflow.md` — Parallel research → merge → validate pattern for data population
- `references/automation-pipeline.md` — Cron + subagent + GitHub Actions automated data update pipeline
- `scripts/validate.py` — CLI tool: `python3 scripts/validate.py validate data/cases.json`, `stats`, `export-csv`
- `scripts/dedup.py` — Duplicate detection: `python3 scripts/dedup.py` (internal), `--check FILE` (batch), `--fix` (interactive)
- `scripts/cases_automation.py` — Full automation: validate + report + export CSV/JSONL + candidate validation
