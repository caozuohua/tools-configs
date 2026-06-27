---
name: python-oss-readiness
description: "Scaffold or polish a Python project to open-source release quality. Covers the 11 standard files (LICENSE, CHANGELOG, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, .editorconfig, .pre-commit, CI workflow, pyproject metadata), uv-specific gotchas, TOML table-ordering bugs, and the pre-release verification checklist."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [python, packaging, open-source, scaffolding, uv, hatchling, pyproject, ci, pre-commit]
    related_skills: [plan, test-driven-development, requesting-code-review]
  references:
    - references/pyproject-toml-gotchas.md
    - references/python-pyproject-pitfalls.md
    - references/open-source-file-skeletons.md
  scripts:
    - scripts/audit_oss.sh
    - scripts/check_links.sh
---

# Python Open-Source Readiness

Use this skill when a Python project needs to look like a credible
OSS release: clean `pyproject.toml` metadata, the 11 standard files
(LICENSE, CHANGELOG, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY,
`.editorconfig`, `.pre-commit-config.yaml`, GitHub Actions CI,
`.gitignore`), lint/format hooks wired, and a documented verification
checklist. Same checklist works for **initialising a fresh project** or
**polishing an existing one** to release quality.

## When to use

- **Initialising** a new Python project: the work that usually gets
  skipped in the "let me just get it running" phase and is hard to
  retrofit later. Especially valuable for uv-managed projects.
- **Polishing** an existing project for a public release, a job
  interview portfolio, or an internal-team library.
- **Bootstrapping a service** that needs to look like an internal
  library: same files, slightly different README framing.

## The 11 standard files

A credible OSS Python project ships these. Templates in `templates/`
are copy-pasteable, with `<PLACEHOLDER>` markers for the per-project
parts.

| File | Purpose |
|---|---|
| `pyproject.toml` | Build config + project metadata (license, classifiers, urls, scripts) |
| `README.md` | First impression: badges, TOC, install, configuration table, usage |
| `LICENSE` | The file, not a sentence (MIT / Apache-2.0 / etc.) |
| `CHANGELOG.md` | Keep a Changelog format with `Unreleased` + versioned sections |
| `CONTRIBUTING.md` | Dev setup, commit style (Conventional Commits), PR flow, link to CoC |
| `CODE_OF_CONDUCT.md` | Contributor Covenant 2.1 (canonical text) |
| `SECURITY.md` | Private reporting channel + response timeline + hardening notes |
| `.editorconfig` | Indent / EOL / charset for cross-editor sanity |
| `.pre-commit-config.yaml` | ruff (lint + format) + general hygiene hooks |
| `.github/workflows/ci.yml` | lint job + test matrix (Python 3.11 + 3.12) |
| `.gitignore` | Includes `.env`, `.secrets/`, `*.db`, venvs, `__pycache__/` |

## Critical gotchas

Each is a real bug that has been hit. The templates in `templates/`
are hardened against them.

### 1. TOML table ordering in `pyproject.toml`

After `[project.urls]`, any new top-level key is **parsed as a
sub-key of the URLs table**, not as a new project field. Symptom:

```
TypeError: URL `dependencies` of field `project.urls` must be a string
```

**Fix:** keep all `[project]` keys contiguous, then `[project.urls]`,
then `[project.optional-dependencies]`, then `[project.scripts]`,
then `[build-system]`, then everything else. See
`templates/pyproject.toml` for the canonical order.

### 2. `uv sync` does not install optional-dependencies

`uv sync` only installs the project + required deps. Dev tools
(`pytest`, `ruff`, `pre-commit`) require explicit opt-in:

```bash
uv sync --extra dev        # [project.optional-dependencies].dev
# NOT
uv sync                    # misses dev extras
```

Update CI workflows accordingly: `uv sync --frozen --extra dev`. Add
the same flag to README install instructions.

### 3. `[dependency-groups]` (PEP 735) vs hatchling

Hatchling's metadata reader trips on PEP 735's `[dependency-groups]`
table and errors out during `uv sync`. Stick with
`[project.optional-dependencies]` for hatchling-backed projects.
PEP 735 is fine for pdm / rye / standalone pip.

### 4. `pytest` config option `timeout` needs a plugin

The `timeout = 60` entry in `[tool.pytest.ini_options]` requires the
`pytest-timeout` plugin. Add it to dev extras, not just the core
`pytest` dep:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-timeout>=2.3.0",   # required for `timeout = 60` config
    ...
]
```

### 5. `ANN` ruff rule floods cosmetic warnings

Adding `ANN` (flake8-annotations) to ruff's `select` triggers
~50 "missing return type annotation" warnings on private helpers
like `_render_page_to_png`. Opt in **module-by-module**, not
globally, until type coverage improves. Default posture: leave
ANN out of `select`, document that in a comment.

### 6. `[tool.ruff.lint.per-file-ignores]` for tests

`tests/*` almost always needs `"ANN", "S101"` to allow untyped
test helpers and bare `assert`. Add this upfront:

```toml
[tool.ruff.lint.per-file-ignores]
"tests/*" = ["ANN", "S101"]
```

### 7. CLI entry-point needs all env vars even for subcommands

A common pattern: `kb progress` (reads local SQLite) crashes because
`run.py` calls `get_settings()` at startup, which validates
`GCP_PROJECT_ID` and `DATABASE_URL`. Two options:

- Defer `get_settings()` into the subcommand handler
- Document that every subcommand needs full env

Pick the first if the project has subcommands that don't need
remote services; pick the second if the entry point is small.

### 8. JSON values in `.env` must be single-quote wrapped

Any `.env` line holding a JSON object/array must be wrapped in
**single quotes** to survive `set -a; . .env` shell sourcing:

```bash
# WRONG — bash parses the inner `"` as a string delimiter and strips them
# The value becomes {a:1} (no quotes), which pydantic-settings then reports
# as "missing" with a confusing ValidationError.
DRIVE_FOLDER_MAP_JSON={"a":"1","b":"2"}

# CORRECT — wrap the whole value in single quotes, leave JSON's own quotes inside
DRIVE_FOLDER_MAP_JSON='{"a":"1","b":"2"}'
```

**Why:** in unquoted shell context, every `"` starts a new
double-quoted string, so `{"a":"1"}` is parsed as `{a:1}` (the `"`
chars vanish). This breaks pydantic-settings JSON validators, which
report the field as "missing" — making the bug look like an unset
variable when it's actually a parsing issue. Same trap hits any
JSON-in-env pattern (drive folder maps, feature flag maps, etc.).

Backslash-escaping (`KEY={\"a\":\"1\"}`) also works but is harder to
read. The `.env.example` template ships the unquoted form for
readability — when copying into `.env`, **always wrap JSON values
in single quotes**.

Quick verification: after editing, run
`set -a && . .env && set +a && python3 -c "import os; print(repr(os.environ.get('KEY')))"`
and check the value still has its `"` chars.

## Recommended: a pre-flight `scripts/doctor.py`

For any project with backing services (DB, cloud APIs, OAuth), add a
`scripts/doctor.py` that pre-flight checks every layer the app
needs before it crashes mid-run. The shape that works:

- Reads `os.environ` directly (or via pydantic-settings) and
  validates required vars
- Checks file paths in env vars exist + are readable
- TCP-probes hosts/ports (`socket.create_connection((host, port), timeout=3)`)
  — no auth, just confirms the network path
- Confirms schema files / migration targets exist
- Exits 0 if all pass, 1 if any fail
- `--json` flag for CI / dashboards
- Friendly per-check output with the `✓ / ✗` mark and a one-line
  next-action hint on failure (e.g. "gsutil mb -l us-central1 gs://...")

This single script catches ~80% of "I just cloned the repo, why
won't it run" issues in one pass. Wire it as the entry to the
verification checklist below:

## Workflow

1. **Plan with the `plan` skill**: write a checklist, list open
   questions for the user, then dispatch one task at a time.
2. **Scaffold in dependency order**:
   `pyproject.toml` → `.gitignore` → source `src/` → `tests/` → CLI
   `__main__` → README. Verify each step before moving on:
   `uv sync --extra dev` + `uv run ruff check .` + `uv run pytest -q`.
3. **Polish to OSS standards**: copy each template from
   `templates/`, replace `<PLACEHOLDER>` markers, commit.
4. **CI**: wire `.github/workflows/ci.yml` BEFORE pushing so a green
   tick is the first thing reviewers see.
5. **Final verification**: walk the checklist below.

## Verification checklist

Before declaring "OSS-ready":

- [ ] `uv sync --extra dev` succeeds
- [ ] `uv run ruff check .` returns `All checks passed!`
- [ ] `uv run ruff format --check .` is clean (run `uv run ruff format .` to fix)
- [ ] `uv run pytest -q` is green (all warnings investigated)
- [ ] `python -m <pkg> --help` (or project entry-point script) prints cleanly
- [ ] `python -c "import <pkg>; print('<pkg> loaded')"` works
- [ ] Every public function has a docstring (run a small AST script to verify)
- [ ] No unused imports
- [ ] No bare `except Exception` without `# noqa: BLE001 — <reason>`
- [ ] `.env.example` exists, `.env` is gitignored
- [ ] JSON values in `.env` are single-quote-wrapped (see gotcha #8)
- [ ] `CHANGELOG.md` has `## [Unreleased]` section
- [ ] `LICENSE` exists, file content matches `license = { text = ... }` in `pyproject.toml`
- [ ] CI workflow installs dev extras: `uv sync --frozen --extra dev`
- [ ] README has badges, TOC, and a Configuration table

A quick AST script for the public-docstring check:

```python
import ast
from pathlib import Path
for path in Path(".").rglob("*.py"):
    if ".venv" in path.parts or "__pycache__" in path.parts:
        continue
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_") and not ast.get_docstring(node):
                print(f"{path}:{node.lineno} {node.name}")
```

## What this skill is NOT

- Not a license-selection advisor — pick MIT unless told otherwise
- Not a PyPI publishing guide — different skill: `pypi-release`
- Not a Docker / container build guide — different skill: `containerize-app`
- Not a SECURITY threat modeler — the `SECURITY.md` template is a
  coordination file, not a risk assessment

## Audit workflow (12-item checklist)

Run this in order when polishing an existing project. Each item is a
separate file or change; bundle into one or two commits at the end.

### 1. LICENSE (1.1 KB)

- Pick a license (MIT is the default for permissive; Apache 2.0 for
  patent grants; GPL for copyleft). Leaving it `All rights reserved`
  is the **opposite** of open-source, not a safe default.
- File at the repo root, named `LICENSE` (or `LICENSE.md` / `LICENSE.txt`).
- Include full license text + copyright year + copyright holder.

### 2. CHANGELOG.md (Keep a Changelog format)

- Two sections minimum: current `## [Unreleased]` + a tagged version
  (e.g. `## [0.1.0] - YYYY-MM-DD`).
- `### Added / ### Changed / ### Fixed` subheaders.
- Every public-facing change documented. No "internal refactor"
  without impact.
- Reference: `https://keepachangelog.com/en/1.1.0/`.

### 3. CONTRIBUTING.md

- Dev setup (`uv sync --extra dev` or equivalent).
- Code style rules (which linter, formatter, exceptions).
- Test instructions (`pytest`, coverage requirements).
- Commit-message convention (Conventional Commits, etc.).
- PR flow (squash? rebase? review required?).

### 4. CODE_OF_CONDUCT.md

- Use [Contributor Covenant 2.1](https://www.contributor-covenant.org/) — most common, no need to write your own.
- Reference your security contact (see SECURITY.md).
- Attribution section at the bottom.

### 5. SECURITY.md

- Reporting channel (private email or GitHub Security Advisories).
- Response timeline table (acknowledgement, triage, patch SLA per severity).
- Out-of-scope list (upstream bugs, attacks requiring pre-existing access).
- Hardening notes for self-hosters (where to put credentials, what to gitignore).

### 6. .editorconfig

- UTF-8, LF, indent style/size per file type.
- `insert_final_newline = true`, `trim_trailing_whitespace = true`.
- `max_line_length` per type (Markdown and YAML often don't need a cap; Python does).

### 7. .pre-commit-config.yaml

- Ruff (format + check) — fastest single tool.
- General hygiene: `trailing-whitespace`, `end-of-file-fixer`, `check-yaml`, `check-toml`, `check-merge-conflict`, `detect-private-key`.
- Pytest as a manual-stage hook (so it doesn't run on every commit, but can be invoked).
- Install once with `uv run pre-commit install`.

### 8. .github/workflows/ci.yml

- Two jobs minimum: `lint` (ruff) + `test` (pytest).
- Matrix on Python versions (3.11 + 3.12 is a sane minimum).
- `uv sync --frozen --extra dev` to install deps with lockfile respected.
- Set dummy env vars so unit tests (no real DB) pass.
- Use `astral-sh/setup-uv@v3` + `astral-sh/ruff-action@v1` for speed.

### 9. pyproject.toml metadata polish

- `description` is one sentence, not a paragraph.
- `keywords` — 5–10 strings, lowercase.
- `classifiers` — at least 5 covering license / audience / python version / topic.
- `license = { text = "MIT" }` — PEP 639 form (or `license = { file = "LICENSE" }` for full text).
- `[project.urls]` — Homepage, Repository, Issues, Changelog.
- `[project.optional-dependencies].dev` (NOT `[dependency-groups]` with hatchling).
- Dependencies in alphabetical-ish or logical groupings with `# --- category ---` comments.

### 10. README.md overhaul

- Badges (Python version, license, CI, code style, package manager) — 3–5 max.
- Table of contents for sections > 5.
- **Features** section with checkmark bullets (each feature = one concrete thing).
- **Configuration** table — every env var with required/default/notes.
- **Architecture** diagram (ASCII is fine) showing data flow.
- **Migration / deployment** section if the project is meant to be deployed.
- **Known gaps** section — honest roadmap. Don't lie about completeness.
- **Contributing** + **License** sections pointing to CONTRIBUTING.md / LICENSE.
- **Every relative link resolves** to a real file (the script in `scripts/check_links.sh` verifies this).

### 11. Lint + format + test baseline

- `ruff check .` returns 0 errors.
- `ruff format --check .` returns 0 files needing reformat.
- `pytest tests/` passes with at least a smoke test.
- CI workflow must reflect this (otherwise the green badge is a lie).
- Public methods have docstrings. (Audit-only check; can be its own task.)

### 12. Markdown link integrity

- Every `[label](path.md)` in every `.md` file resolves to a real file in the repo.
- URLs starting with `http` are external (OK to leave unverified).
- Anchor links (`#section`) are not checked by the static script — but verify visually for key sections.
- `docs/` directory entries match the README's "Architecture" / "Key docs" references.

## Two-pass execution pattern

For maximum efficiency, run the audit in two passes.

**Pass 1 — Static checks (automated):**

1. `ls LICENSE CHANGELOG.md CONTRIBUTING.md CODE_OF_CONDUCT.md SECURITY.md .editorconfig .pre-commit-config.yaml .github/workflows/ci.yml pyproject.toml README.md` — which are missing.
2. `ruff check .` and `ruff format --check .` for code state.
3. Markdown link scan (the one-liner in `scripts/check_links.sh`).
4. `bash scripts/audit_oss.sh` for a consolidated first-pass report.

**Pass 2 — Manual review (judgment):**

1. Read README.md top-to-bottom. Badges, TOC, Features, Configuration, Architecture, Known gaps — all present and accurate?
2. Read CHANGELOG.md. Does it match what's actually in the repo?
3. Read CONTRIBUTING.md. Would a new contributor be able to set up the project from this alone?
4. Open pyproject.toml. Classifiers, keywords, URLs all present?
5. Spot-check: pick 3 random doc links in README, follow each, confirm file exists.

## Code-level polish (often paired with the audit)

Before walking the 12-item checklist, sweep the codebase:

1. `find . -not -path '*/.venv/*' -not -path '*/.git/*' -not -path '*/.pytest_cache/*' -type f | sort` — inventory.
2. Run `ruff` with a wide `select` to catch dead imports, style drift, blind except, pyupgrade.
3. Run the existing test suite to establish baseline.
4. Identify: dead imports, missing docstrings on public methods, logging inconsistencies (stdlib vs structlog), bare `except Exception` without `# noqa`, magic numbers without named constants.

**Fast wins:**

- Delete unused imports
- Resolve logging library to stdlib (don't mix structlog with stdlib)
- Add docstrings to all public functions/methods (Google style)
- Add `# noqa: BLE001 — <reason>` to intentional broad-except sites
- Promote magic numbers to module-level constants with rationale comments

## Common pitfalls (audit + scaffold combined)

| Pitfall | Fix |
|---|---|
| TOML `dependencies` written after `[project.urls]` → parsed as URL key | Move `dependencies = [...]` to be inside `[project]` (before any subsection) |
| `uv sync` doesn't install dev extras | `uv sync --extra dev` (and same in CI workflow) |
| `hatchling` build fails on `[dependency-groups]` (PEP 735) | Use `[project.optional-dependencies].dev` for dev deps |
| `pytest` warns about `Unknown config option: timeout` | Add `pytest-timeout` to dev deps |
| Hardcoded values from a reference design don't match your config | Make them dynamic — read from `settings` |
| README references docs that don't exist | Create the docs (even minimal) or remove the references |
| `except Exception` fails ruff BLE001 | Add `# noqa: BLE001 — <reason>` (the reason is required) |
| `from typing import Sequence` → UP035 | `from collections.abc import Sequence` |
| Subagent created `__init__.py` that wasn't asked for | Be explicit in the spec about file additions |
| Missing `__init__.py` in `tests/` blocks package-mode pytest | Either add it or rely on conftest.py + pyproject's testpaths |
| Embedding model locked but README doesn't say so | Add to "Design decisions" or "Known limitations" — explicit assumptions survive refactors |
| API enable / SA role list lives in someone's head | Add `docs/gcp-setup.md` (or equivalent) — the step that's "obvious" to you is invisible to a new contributor |
| TOML table continuation: `dependencies = [...]` after `[project.urls]` gets parsed as a sub-key | Keep the `[project]` table contiguous — declare new sub-tables only after all `[project]` keys |
| PEP 735 `[dependency-groups]` triggers hatchling metadata error | Use only `[project.optional-dependencies]` (PEP 621) |
| `psycopg.ConnectionPool` doesn't exist | `from psycopg_pool import ConnectionPool` — `ConnectionPool` lives in `psycopg_pool`, not in `psycopg` |
| Monkey-patching import-time aliases | When a module does `from other_module import func as alias`, patching `other_module.func` later does NOT affect `my_module.alias` — patch the alias directly |
| Pydantic Settings validates all required fields at instantiation | Defer `get_settings()` to the subcommand that needs them, or make all settings optional |

For pyproject.toml-specific gotchas with copy-pasteable fixes, see
`references/pyproject-toml-gotchas.md` and `references/python-pyproject-pitfalls.md`.
For full text of LICENSE / CHANGELOG / CONTRIBUTING / CoC / SECURITY / .editorconfig /
.pre-commit-config.yaml, see `references/open-source-file-skeletons.md`.

## README ordering (order matters)

1. Title + 5 badges (Python / License / linter / package manager / CI)
2. One-line description with link
3. Table of contents (8-10 sections)
4. **Features** (bulleted checklist with checkmarks)
5. **Architecture** (ASCII flow diagram — readable on Discord mobile)
6. **Quick start** (install + first run)
7. **Configuration** (env var table — every var with required/default/notes)
8. **CLI usage** (subcommand list)
9. **Migration** (if applicable — e.g. GCP→Supabase)
10. **Development** (testing, linting, hooks)
11. **Project layout** (annotated tree)
12. **Known gaps** (honest roadmap — not "TODO" handwave)
13. Contributing link
14. License

**Discord mobile note:** README renders in mobile clients. Avoid wide
markdown tables; use bullet lists instead. ASCII flow diagrams render fine.

## How this user prefers to work

- **Concise progress reports** after each batch of changes — "what I
  did, what passed, what's next" in bullets
- **End-to-end completion** — they don't want to be re-prompted for
  every small decision
- **Flag deviations explicitly** with rationale and offer to revert
- **Bullet lists over wide tables** for Discord mobile readability
- **One task at a time for big features** but **batch polish work** in
  one go
- **No hand-waving on "TODO"** — list known gaps honestly in the
  README

## Bundled scripts and references

- `scripts/audit_oss.sh` — first-pass static check for the 12-item
  audit. Run this and fix everything it flags before doing the manual
  pass.
- `scripts/check_links.sh` — markdown link integrity scan. Run this
  AFTER any README rewrite.

Both scripts are designed to be run from the repo root with no arguments.
Reference docs with the full per-gotcha write-ups and skeleton text for
the standard files live in `references/`.
