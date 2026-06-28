# 🛠️ tools-configs

[![Skills](https://img.shields.io/badge/skills-39-blue.svg)](./skills)
[![Scripts](https://img.shields.io/badge/scripts-3-green.svg)](./scripts)
[![License](https://img.shields.io/badge/license-MIT-lightgrey.svg)](#license)
[![Hermes Agent](https://img.shields.io/badge/hermes-agent-orange.svg)](https://hermes-agent.nousresearch.com)

A curated collection of custom Hermes Agent skills, utility scripts, and configuration templates — battle-tested infrastructure knowledge accumulated from real-world debugging, deployment, and development workflows.

> Every skill, script, and config in this repo came from a real production incident or workflow — not a demo, not a tutorial.

---

## Table of Contents

- [Project Structure](#project-structure)
- [Skills](#skills)
  - [Software Development](#software-development)
  - [DevOps & Infrastructure](#devops--infrastructure)
  - [MLOps & Search](#mlops--search)
  - [GitHub](#github)
  - [Research & Cases](#research--cases)
  - [Agent & Formatting](#agent--formatting)
- [Scripts](#scripts)
- [Configuration Templates](#configuration-templates)
- [Quick Start](#quick-start)
- [Skill Reference Documents](#skill-reference-documents)
- [Contributing](#contributing)
- [License](#license)

---

## Project Structure

```
tools-configs/
├── skills/                          # Hermes Agent skills (SKILL.md format)
│   ├── software-development/        # Development workflows, code quality, debugging
│   ├── devops/                      # Infrastructure, security, deployment
│   ├── mlops/                       # ML engineering, search, models
│   ├── github/                      # GitHub API operations
│   ├── research/                    # Research tools & case collections
│   ├── hermes-agent/                # Hermes Agent configuration & extension
│   ├── gcp-vps-ops/                 # GCP VPS operations (with sub-skill + references)
│   ├── nanobot-vps-deployment/      # Nanobot VPS deployment
│   ├── discord-mobile-formatting/   # Discord message formatting
│   ├── google-genai-python-sdk/     # Google GenAI SDK guide
│   ├── avoid-false-positive-warnings/
│   └── agent-response-critique/
├── scripts/                         # Standalone Python utility scripts
│   ├── vertexai_proxy.py
│   ├── vertex_gemini.py
│   └── vps-watchdog.py
├── configs/                         # Configuration file templates
│   ├── vertexai-proxy.yaml
│   └── config.yaml
├── references/                      # Shared reference documents
└── .gitignore
```

---

## Skills

### Software Development

| Skill | Description |
|-------|-------------|
| `plan` | Write actionable markdown implementation plans with bite-sized tasks, exact paths, and complete code |
| `subagent-driven-development` | Execute plans via `delegate_task` subagents with two-stage review (spec → quality) |
| `simplify-code` | Parallel 3-agent cleanup of recent code changes (reuse, quality, efficiency reviewers) |
| `test-driven-development` | Enforce RED-GREEN-REFACTOR cycle — write tests before code |
| `spike` | Throwaway experiments to validate an idea before committing to a build |
| `systematic-debugging` | 4-phase root cause debugging: understand bugs before fixing them |
| `requesting-code-review` | Pre-commit review with security scan, quality gates, and auto-fix |
| `incremental-audit-and-fix` | Per-file audit checklist with strict one-task-at-a-time fix gates |
| `api-hardening` | Cleanup and hardening pass on deployed APIs — auth middleware, validation, curl matrix verification |
| `llm-agent-execution-patterns` | Diagnose LLM agents that announce plans but fail to execute |
| `agent-framework-design-analysis` | Analyze reference agent frameworks and extract transferable design lessons |
| `hermes-agent-skill-authoring` | Write high-quality SKILL.md files with proper frontmatter and structure |
| `hermes-provider-integration` | Wire a new LLM provider/model API into Hermes Agent |
| `markdown-to-html-email` | Robust Markdown → HTML conversion tuned for email clients |
| `multi-agent-data-validation` | Multi-agent parallel proofreading/cleaning workflow for JSON datasets |
| `static-data-scaffold` | Scaffold a JSON-driven static site for GitHub Pages with search, filters, and tags |
| `codegraph` | Codebase structural analysis — map dependencies and trace logic flow |
| `rag-ingestion-pipeline` | Build or refactor a personal RAG knowledge base on GCP (Drive → parsers → embeddings → pgvector) |
| `python-oss-readiness` | Scaffold or polish a Python project to open-source release quality |
| `node-inspect-debugger` | Debug Node.js via `--inspect` + Chrome DevTools Protocol CLI |
| `writing-plans` | Writing plan discipline (directory placeholder) |
| `finishing-a-development-branch` | Branch completion workflow (directory placeholder) |
| `executing-plans` | Plan execution workflow (directory placeholder) |
| `dispatching-parallel-agents` | Parallel agent dispatching patterns (directory placeholder) |
| `finding-duplicate-functions` | Duplicate function detection (directory placeholder) |
| `verification-before-completion` | Verify results before claiming completion (directory placeholder) |
| `python-debug-py` | Python debugging utilities (directory placeholder) |

### DevOps & Infrastructure

| Skill | Description |
|-------|-------------|
| `hermes-vertexai-provider` | Wire Google Vertex AI / Gemini into Hermes via the OpenAI-shape HTTP proxy (includes 5 known 400 bug workarounds) |
| `hermes-multi-profile` | Diagnose and fix Hermes multi-profile setups with systemd `Environment=HERMES_HOME` |
| `hermes-transport-redactor-workarounds` | Workarounds for Hermes transport-layer credential redaction when writing files or building commands |
| `cloudflare-vps-edge-protection` | Add Cloudflare Access + Tunnel + R2 backup to a personal VPS using free tier |
| `headless-google-oauth` | Authenticate Google APIs from headless servers via InstalledAppFlow URL paste-back |
| `xray-reality-deployment` | Set up, upgrade, and troubleshoot VLESS + XTLS-Vision + Reality proxy via x-ui |
| `x-ui-and-new-api-security-posture` | Harden x-ui panel + new-api API gateway on VPS with nginx SNI 443 routing |
| `nanobot-vps-deployment` | Deploy and operate the nanobot fork on a constrained VPS with lean-first approach |
| `gcp-vps-ops` | Operate on GCP VPS instances via `gcloud` SSH — service users, SQLite, OS Login |
| `pkb-knowledge-base` | PKB personal knowledge base architecture (deprecated — for historical reference only) |

### MLOps & Search

| Skill | Description |
|-------|-------------|
| `gcp-google-search-via-genai` | Call Google Search via local VertexAI proxy as a `web_search` fallback when quota is exhausted |
| `google-genai-python-sdk` | Full Google GenAI Python SDK guide — Vertex AI & Gemini API modes, streaming, function calling, thought signatures |

### GitHub

| Skill | Description |
|-------|-------------|
| `github-workflow-file-update` | Update GitHub Actions workflow files via REST API, with workflow-scope & 404/403 diagnosis |

### Research & Cases

| Skill | Description |
|-------|-------------|
| `mem0-research` | Mem0 memory layer research — open-source AI agent personalization engine (YC S24) |
| `power-digital-cases` | Power industry digitalization case collection — 483 cases / 50+ countries / 28 standard tags |

### Agent & Formatting

| Skill | Description |
|-------|-------------|
| `hermes-agent` | Configure, extend, or contribute to Hermes Agent |
| `discord-mobile-formatting` | Format messages for Discord mobile readability — avoid tables, use lists |
| `avoid-false-positive-warnings` | Cross-check daemon/agent WARNING/ERROR output against actual system state before acting |
| `agent-response-critique` | Evaluate whether an AI agent's response is genuinely reflective or confabulated — cross-reference claims against logs |

---

## Scripts

| Script | Description | Dependencies |
|--------|-------------|--------------|
| `vertexai_proxy.py` | Vertex AI Gemini proxy — OpenAI-shape HTTP frontend over `google-genai` (~200 LOC, listens on `127.0.0.1:18999`) | `google-cloud-aiplatform`, `google-genai` |
| `vertex_gemini.py` | Side-channel Gemini API caller via `google-genai` + ADC (no Hermes core changes needed) | `google-genai` |
| `vps-watchdog.py` | VPS health check via single SSH roundtrip — swap, memory, disk thresholds; exits 0/1/2 for cron integration | `requests` (optional) |

### GCP VPS Ops Scripts

Located under `skills/gcp-vps-ops/gcp-vps-ops/scripts/`:

| Script | Description |
|--------|-------------|
| `merge-hermes-profile-config.py` | Merge Hermes profile configuration files |
| `vps-watchdog.py` | VPS health monitor (same as above, bundled with the skill) |
| `update-hermes.sh` | Update Hermes Agent installation |
| `monitor-nanobot.sh` | Monitor nanobot service health |

---

## Configuration Templates

| File | Description |
|------|-------------|
| `configs/vertexai-proxy.yaml` | Hermes + VertexAI proxy configuration — model list, rate limits, thinking budget |
| `configs/config.yaml` | Full Hermes Agent configuration template — model, terminal, browser, TTS, memory, delegation, and more |
| `configs/auth.json` | Provider credential pool template (gitignored — never commit real credentials) |

> ⚠️ `auth.json` and `config.yaml` contain sensitive fields and are listed in `.gitignore`. The checked-in versions are templates only.

---

## Quick Start

### 1. Start the VertexAI Proxy

```bash
cd tools-configs

# Install dependencies
pip install google-cloud-aiplatform google-genai

# Start the proxy (foreground for dev)
python scripts/vertexai_proxy.py
# → Proxy listening on http://127.0.0.1:18999

# Or run in background for production
python scripts/vertexai_proxy.py &
```

Configure Hermes to use the proxy by pointing a provider's `base_url`:

```yaml
# In your Hermes config
model:
  default: vertexai/gemini-3.5-flash
  provider: vertexai
  base_url: http://127.0.0.1:18999/v1
  api_key: not-used-by-proxy-any-string-works
```

### 2. Install a Skill

Copy any skill directory into your Hermes skills folder:

```bash
# Example: install the plan skill
cp -r skills/software-development/plan ~/.hermes/skills/software-development/

# Example: install a DevOps skill
cp -r skills/devops/cloudflare-vps-edge-protection ~/.hermes/skills/devops/

# Install all skills at once
cp -r skills/* ~/.hermes/skills/
```

### 3. Run the VPS Watchdog

```bash
# One-shot health check
python scripts/vps-watchdog.py

# Add to crontab (every 10 minutes)
crontab -e
# */10 * * * * /path/to/venv/bin/python /path/to/tools-configs/scripts/vps-watchdog.py
```

### 4. Use the VertexAI Direct Caller

```bash
# Single prompt
python scripts/vertex_gemini.py "Explain quantum entanglement in one paragraph"

# Pipe input
echo "Summarize this document" | python scripts/vertex_gemini.py -
```

---

## Skill Reference Documents

The `gcp-vps-ops` skill includes a rich set of operational reference documents under `skills/gcp-vps-ops/gcp-vps-ops/references/`:

| Reference | Topic |
|-----------|-------|
| `ssh-connection-diagnosis.md` | SSH connectivity troubleshooting |
| `session-2026-06-10.md` | Operational session log |
| `service-secret-and-bot-audit.md` | Service credentials & bot audit |
| `hermes-lite-profile-sync.md` | Hermes lite profile synchronization |
| `hermes-redactor-workarounds.md` | Credential redaction workarounds |
| `hermes-feishu-gateway-deployment.md` | Feishu (Lark) gateway deployment |
| `nanobot-deployment.md` | Nanobot deployment on VPS |
| `pkb-api-quirks.md` | PKB API known issues |
| `lark-api-write-via-remote-vps.md` | Lark API write operations via remote VPS |
| `lark-open-api-scopes.md` | Lark Open API permission scopes |
| `reality-vpn-architecture.md` | VLESS + Reality VPN architecture |
| `luck-agent-architecture.md` | Luck agent system architecture |
| `google-genai-proxy.md` | Google GenAI proxy design |
| `remote-execution.md` | Remote execution patterns |
| `gcp-vps-instances.md` | GCP VPS instance inventory |
| `lark-oapi-python-sdk-quirks.md` | Lark OAPI Python SDK known issues |
| `sparse-checkout-and-lean-venv.md` | Git sparse checkout + lean virtualenv |
| `vps-health-watchdog.md` | VPS health watchdog design |
| `certbot-webroot-with-stream.md` | Certbot webroot with nginx stream |

---

## Contributing

Contributions are welcome! Here's how to add new content:

### Adding a New Skill

1. Create a directory under the appropriate category:
   ```
   skills/<category>/<skill-name>/SKILL.md
   ```
2. Write the `SKILL.md` with proper YAML frontmatter:
   ```yaml
   ---
   name: your-skill-name
   description: "One-line description of what this skill does"
   version: 1.0.0
   author: Your Name
   license: MIT
   platforms: [linux, macos, windows]
   metadata:
     hermes:
       tags: [tag1, tag2]
       related_skills: [other-skill]
   ---
   ```
3. Follow the content structure from existing skills — include when-to-use triggers, step-by-step process, and pitfalls.

### Adding a New Script

1. Place it in `scripts/`
2. Add a shebang line: `#!/usr/bin/env python3`
3. Make it executable: `chmod +x scripts/your-script.py`
4. Include a module docstring with usage instructions and environment variable overrides

### Adding a New Config Template

1. Place it in `configs/`
2. Add sensitive files to `.gitignore`
3. Document the config in this README

### General Guidelines

- **Real-world only**: Every entry should trace back to a genuine production need or debugging session
- **Keep it focused**: One skill per concern; one script per job
- **Document env vars**: If a script accepts environment variables, document them in the docstring
- **Test before committing**: Verify scripts and skills work before pushing

---

## License

This repository is provided under the [MIT License](https://opensource.org/licenses/MIT). Individual skills may carry their own license notices in their SKILL.md frontmatter.

---

*These tools were forged in real production fire — not demos, not tutorials. Every entry represents a lesson learned the hard way.*
