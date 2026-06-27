---
name: github-workflow-file-update
description: "Update GitHub Actions workflow files (.github/workflows/*.yml) via REST API. Covers the workflow-scope requirement, 404-vs-403 diagnosis, and fallback strategies when token lacks workflow scope."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [github, actions, workflow, api, permissions, ci]
    related_skills: [github-auth, github-repo-management]
---

# GitHub Actions Workflow File Update

Update `.github/workflows/*.yml` files via the GitHub REST API. Handles the special `workflow` scope requirement and common failure modes.

## Problem

When trying to update `.github/workflows/*.yml` via `PUT /repos/{owner}/{repo}/contents/{path}`, you get **404 Not Found** even though:
- The file exists (GET returns 200 with correct SHA)
- The token has `repo` scope
- Other files in the same repo update fine

## Root Cause

GitHub requires the **`workflow`** scope (not just `repo`) to modify files under `.github/workflows/`. The error is **404** (not 403), which is misleading.

## Diagnosis

```bash
# Check token scopes
gh api user -H "Authorization: Bearer *** auth token)" 2>&1 | head -5
# Look for response header: X-Oauth-Scopes
# If "workflow" is missing, that's the problem
```

## Solution

Regenerate the Personal Access Token with `workflow` scope:
1. https://github.com/settings/tokens
2. Add `workflow` scope
3. Update `~/.config/gh/hosts.yml` or re-auth: `gh auth login --scopes repo,workflow`

## Update Pattern (with correct scope)

```python
import requests, base64, json

# Read token from gh config
with open('~/.config/gh/hosts.yml') as f:
    for line in f:
        if 'oauth_token' in line:
            token = line.split(':')[1].strip()

# Get current file SHA
resp = requests.get(
    "https://api.github.com/repos/OWNER/REPO/contents/.github/workflows/FILE.yml",
    headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
)
sha = resp.json()["sha"]

# Update
content = base64.b64encode(new_file_content.encode()).decode()
payload = json.dumps({
    "message": "ci: update workflow",
    "content": content,
    "sha": sha,
    "branch": "main"
})

resp = requests.put(
    "https://api.github.com/repos/OWNER/REPO/contents/.github/workflows/FILE.yml",
    headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "Content-Type": "application/json"},
    data=payload
)
```

## Fallback (no workflow scope)

If you can't change token scope:
1. Use GitHub web interface: `github.com/OWNER/REPO/edit/main/.github/workflows/FILE.yml`
2. Create a commit via git push (if token has `repo` scope, git push works for workflow files)
3. Create a PR from a fork

## Affected Endpoints

| Endpoint | `repo` | `workflow` |
|----------|:---:|:---:|
| `GET /contents/.github/workflows/*` | ✅ | ✅ |
| `PUT /contents/.github/workflows/*` | ❌ 404 | ✅ |
| `POST /git/trees` (workflow path) | ❌ 404 | ✅ |

## Validated

2026-06-26 on `caozuohua/ai-daily-newsletter`.
