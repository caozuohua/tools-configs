---
name: codegraph
description: Codebase structural analysis, mapping dependencies, and tracing logic flow.
category: software-development
---

# CodeGraph: Codebase Structural Analysis

This skill enables the agent to build, maintain, and query a structural map of a codebase to navigate complex logic without reading every file.

## Trigger Conditions
- User asks "Where is X implemented?" or "How does X relate to Y?"
- New codebase encountered for the first time.
- Large-scale refactoring required.
- Onboarding to a new project.

## Workflow

### 1. Initial Mapping (The Scan)
When first entering a codebase, perform a structural scan:
1. **File Tree**: Use `search_files(target='files', pattern='*')` to understand the directory hierarchy.
2. **Entry Points**: Locate main entry points (e.g., `main.py`, `app.py`, `index.ts`, `cli.py`).
3. **Dependency Graph**: 
   - Use `rg` to search for import statements (`import ...`, `from ... import ...`).
   - Map which modules depend on which.
4. **Key Logic Hubs**: Identify "god-files" or central managers (usually files with high import counts).

### 2. Deep Dive (The Trace)
To trace a specific feature:
1. **Define Target**: Identify the keyword/function name.
2. **Find Definitions**: Use `rg` to find the exact definition site.
3. **Trace Callsites**: Search for all locations where that function/class is instantiated or called.
4. **Build Sequence**: Construct a logical flow: `User Input` $\rightarrow$ `Handler` $\rightarrow$ `Service` $\rightarrow$ `Database/API`.

### 3. Maintenance
- After making structural changes, re-run the scan to update the internal map.
## Pitfalls & Tips

- **Don't blindly `cat`**: Never read a 2000-line file just to find one function. Use `rg` first.
- **Avoid `ls -R`**: Use `search_files` or `fd` for better performance and filtered results.
- **Context Window**: When presenting the graph, use a simplified Markdown list or a mermaid diagram to avoid flooding the context.
- **Non-destructive cleanup default**: When the user asks to "clean up" a directory that holds knowledge/artifact content (notes/, docs/, references/, content/ — but NOT build artifacts, node_modules/, dist/, .next/), default to **content-based classification** of junk, not heuristic bulk deletion. Show the user exactly what will be removed before doing it. If they correct you ("restore them, only remove X"), do restore-then-surgical-delete, not "delete everything and let them re-add". Knowledge/artifact directories accumulate value even when they look messy.
- **Vercel auto-commit + git rebase pitfall**: When a codebase is Vercel-deployed (or any CI that auto-commits back to the repo — file syncs, doc rebuilds, serverless storage mirroring, etc.), the remote accumulates commits you don't see locally. **Always `git pull --rebase` first**, then do your work on top of `origin/main`. If you `git reset --hard` to an old ancestor commit, make changes, then rebase onto origin/main, the rebase will **silently drop** files that the auto-deploy deleted between those points. Symptom: `git ls-files` shows far fewer files than `git log --all` would suggest, and your commit only carries the diff against the old HEAD — losing all the intermediate state. Fix: reset to `origin/main` (not to a local ancestor), or cherry-pick the ancestor's relevant content onto a fresh `origin/main` checkout.

## Cross-Project Integration Analysis

When you have two related codebases (caller + service, app + library, client + server), the goal is to map which surfaces of the dependency are actually consumed.

**Pattern:**

1. **Keyword sweep on the caller side** — search for the dependency's name/url/env var:
   ```bash
   rg -n -i "pkb" --type py            # in luck-agent (Python)
   rg -n "PKB_.*_URL|API_SECRET"      # config-driven integration points
   ```

2. **Keyword sweep on the service side** — find the matching functions/endpoints:
   ```bash
   rg -n "function.*ingest|function.*search"   # in pkb (TypeScript)
   ```

3. **Map the diff** — list which endpoints are AVAILABLE vs. which are CALLED. This reveals:
   - Dead code on the service (endpoints nobody calls)
   - Missing features on the caller (operations the user can't perform)

4. **Build the call graph** — for each consumed endpoint, trace from entry point (handler/route) → intent router → tool schema → HTTP client. This shows the full path of a feature.

**Output format** (mobile-friendly lists, no tables):

- *Currently called*: list of endpoints and the tool/function that calls them
- *Available but not wired*: list of endpoints with the command/feature that would expose them
- *Opportunity*: one-line follow-up suggestion

This pattern caught real opportunities in PKB ↔ luck-agent: the new CRUD endpoints (GET/PATCH/DELETE/list) were unused by luck-agent, so adding `/pkb list` and `/pkb delete` commands would close the gap.

## References

- `references/vercel-auto-deploy-workflow.md` — pitfalls and safe git workflow when the analyzed repo is Vercel-deployed (or any auto-committing CI). Covers the rebase pitfall, the non-destructive cleanup default for mirror directories, and a pre-deletion checklist.
- `references/llm-prompt-architecture.md` — reading order, design-pattern checklist, and pitfalls for analyzing an LLM agent framework's prompt/template/tool-design subsystem (e.g. when the user asks "analyze X's prompt design" or "how does X structure system prompts").

## See also

- **`api-hardening`** — once this skill drafts a P0/P1/P2 issue list
  (especially for "5 routes duplicate the same auth check" or
  "validation missing on public surface"), hand off to `api-hardening`
  for the prioritized implementation pass: extract middleware, add
  defense-in-depth validation, ship bug fixes, verify with a curl
  matrix post-deploy.

## Verification
A successful CodeGraph result should answer:
- What is the entry point?
- Where is the core business logic?
- What are the primary dependencies?
- How does data flow from input to output?