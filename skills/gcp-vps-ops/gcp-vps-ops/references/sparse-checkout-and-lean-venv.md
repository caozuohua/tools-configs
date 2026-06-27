# Git sparse-checkout + Lean venv for Constrained VPS

When deploying a large Python project (1+ GB on disk) to a constrained VPS
(1 GB RAM, <30 GB disk), the goal is to ship only what actually runs.

## sparse-checkout for big repos (Hermes-agent pattern)

`git clone` followed by `rm -rf <big_dir>` does NOT work — `git pull` will
re-create the tracked files. Use sparse-checkout instead:

```bash
git clone --filter=blob:none --sparse https://github.com/Org/big-repo.git
cd big-repo
git sparse-checkout init --cone
git sparse-checkout set dir1 dir2 dir3 ...   # only these dirs land on disk

# Verify: only listed dirs are checked out
ls
du -sh .
```

Why this works:
- `--filter=blob:none --sparse` = partial clone, fetches no blobs until requested
- `sparse-checkout init --cone` = sparse-checkout mode, only specified paths
- Subsequent `git fetch` / `git pull` respects the sparse-checkout set
- Network transfer stays small on updates

When to **re-run sparse-checkout set** (important for update scripts):
- After upgrading hermes-agent via `update-hermes.sh` or similar
- If a previous run accidentally broadened the set
- Cheap operation (~10 ms) — include it in every update step for safety

Reference: hermes-agent full clone = 1.8 GB; sparse-checkout (6 dirs: hermes_cli agent plugins providers cron scripts) = ~55 MB on disk (verified 2026-06-18 on instance-20260413-080555). Saved: ~1.77 GB. The full Hermes Lite deployment (sparse clone + venv + skills) totals 322 MB: venv 260 MB + hermes-agent 55 MB + skills 8 MB.

## CRITICAL: cone mode vs non-cone mode — and what `/*` means

`git sparse-checkout set <dirs>` has TWO modes and the difference is which root-level files survive:

**Cone mode** (the default after `git sparse-checkout init --cone`):
- Auto-includes the magic pattern `/*` + `!/*/` in the sparse-checkout config
- `/*` = "all files in the root" (so `pyproject.toml`, `setup.py`, `MANIFEST.in`, `setup-hermes.sh`, `Dockerfile`, etc. survive)
- `!/*/` = "exclude all top-level directories" (so `agent/`, `cron/` etc. are NOT pulled unless explicitly listed)
- You then `sparse-checkout set agent cron hermes_cli ...` to add the dirs you want
- **This is the right mode for `pip install -e .` projects** — pyproject.toml/setup.py stay on disk

**Non-cone mode** (if you pass `--no-cone`):
- The `/*` and `!/*/` magic is gone
- `sparse-checkout set agent cron hermes_cli ...` ONLY pulls those dirs
- **Root files like `pyproject.toml`, `setup.py`, `MANIFEST.in` are GONE** — `pip install -e .` fails with `does not appear to be a Python project: neither 'setup.py' nor 'pyproject.toml' found.`
- Symptom: `git sparse-checkout set --no-cone agent cron hermes_cli` succeeds, but `git read-tree -mu HEAD` only fills the dirs — root is empty

**The bug I hit 2026-06-18**: ran `git sparse-checkout set --no-cone agent cron hermes_cli plugins providers scripts gateway` to add `gateway/`. The `--no-cone` was a mistake — I lost `pyproject.toml`. Subsequent `pip install -e .` failed with `does not appear to be a Python project`. Fix: reinit cone mode and re-set:
```bash
git sparse-checkout init --cone
git sparse-checkout set agent cron hermes_cli plugins providers scripts gateway
git read-tree -mu HEAD
# pyproject.toml, setup.py, MANIFEST.in reappear
pip install -e .   # now works
```

**How to tell which mode you're in**:
```bash
cat .git/info/sparse-checkout
# cone: contains "/*" and "!/*/" lines + your dirs
# non-cone: just your dirs, no "/*"
```

**`git sparse-checkout add` quirk**: `add` only works in non-cone mode (and the help warns `unrecognized pattern: 'agent'; disabling cone pattern matching`). To ADD a dir while staying in cone mode, use `set` with the full new list — `set` is idempotent.

## CRITICAL: editable install MAPPING becomes stale after sparse-checkout changes

When you run `pip install -e .`, pip generates a `__editable___<pkg>_<ver>_finder.py` in `site-packages/` whose `MAPPING` dict points each top-level package name to its absolute source path. Example from `hermes_agent-0.16.0`:
```python
MAPPING = {
    'hermes_constants': '/home/user/.hermes-lite/hermes-agent/hermes_constants',
    'gateway': '/home/user/.hermes-lite/hermes-agent/gateway',
    'tools': '/home/user/.hermes-lite/hermes-agent/tools',
    ...
}
```

If you **change** the sparse-checkout set (add or remove dirs), the MAPPING may reference paths that don't exist (if the dir was removed) or may be missing new dirs (if the dir was added but you haven't re-run `pip install -e .`).

**Symptom**: `ModuleNotFoundError: No module named 'gateway'` or `No module named 'tools'` — even though `ls /home/user/.hermes-lite/hermes-agent/gateway/` shows the dir exists.

**Fix**: after every sparse-checkout change, re-run:
```bash
cd /home/user/.hermes-lite/hermes-agent
pip install -e .   # regenerates MAPPING with current sparse state
```
This is fast (~10s) and idempotent. **Don't** try to manually edit `__editable___hermes_agent_X_X_X_finder.py` — pip overwrites it on next install and editing the wrong line causes subtle import errors.

## Hidden dirs that get pulled when you `sparse-checkout add` new dirs

When you add a new top-level dir to an existing sparse-checkout set (e.g. adding `gateway/` to `agent cron hermes_cli ...`), `git read-tree -mu HEAD` may pull OTHER top-level dirs that were sparse-excluded. Observed 2026-06-18 on hermes-agent: after adding `gateway/`, `apps/`, `optional-skills/`, `tests/`, `ui-tui/`, `web/`, `website/` showed up uninvited — pulling ~24 MB more than expected. Discovered via `git status` reporting `35% of tracked files present` instead of the expected lower number.

**Fix if this happens**:
```bash
# After adding new dirs, re-run `set` with ONLY the dirs you want
git sparse-checkout set agent cron hermes_cli plugins providers scripts gateway tools
git read-tree -mu HEAD
# Unwanted dirs (apps/tests/website) are now removed
```

The cone mode `set` is idempotent and exactly restores the desired dir set, unlike `add` which can leak.

## Discovering which top-level dirs are actually needed at import time

The editable install MAPPING tells you EXACTLY which Python packages are in use. For hermes-agent:
```
agent, batch_runner, cli, cron, gateway, hermes_bootstrap, hermes_cli, hermes_constants,
hermes_logging, hermes_state, hermes_time, mcp_serve, model_tools, plugins, providers,
run_agent, toolset_distributions, toolsets, trajectory_compressor, utils
```
Plus namespace packages not in MAPPING but still required (e.g. `tools/` for `tools.managed_tool_gateway` — found via `ModuleNotFoundError` when running `hermes gateway`).

**Process for sparse-checkout discovery on a new repo**:
1. `git clone --filter=blob:none --sparse`
2. `git sparse-checkout init --cone`
3. Pull the MAPPING from site-packages (after a `pip install -e .` on a FULL clone somewhere) — gives you the must-have dirs
4. Pull the ENTRY POINTS from `pyproject.toml` `[project.scripts]` — these are your CLI commands
5. Pull any dirs the entry points import (read the entry point source)
6. `git sparse-checkout set <comprehensive_list> && git read-tree -mu HEAD`

This is more reliable than guessing "which dirs does the CLI need" because it traces the actual Python imports.

## Lean venv pattern

Default `pip install -e .` pulls in `setup.py` / `pyproject.toml` declared deps,
including heavy native ones. Audit after install:

```bash
# After pip install, check what's actually loaded
pip list --format=freeze > /tmp/installed.txt
# Walk imports of the actual entry point to find unused packages
# Common heavy unused deps in Python projects:
#   - ctranslate2 (133 MB w/ native libs) — only if you do CTranslate2 inference
#   - onnxruntime (51 MB) — only if you do ONNX inference
#   - pytorch (500+ MB) — only if you do training/embedding
#   - tensorflow, jax, etc.

# Trim: pip uninstall <unused_pkg> — verify the app still imports OK
#         python -c "import <entry_point>" ; echo "OK"
```

Reference: hermes-agent full venv = 662 MB; lean (no ctranslate2, onnxruntime) = 260 MB (verified 2026-06-18, hermes-agent 0.16.0 + lark-oapi 1.6.8 + websockets 15.0.1). Saved: 400 MB. Add lark-oapi for Lark WS bot use case: +5 MB on disk but +~170 MB RSS at runtime (Python + aiohttp + websockets is heavy).

## Update script pattern (strategy C — atomic rollback)

Combine sparse-checkout + lean venv into a single update script:

```bash
#!/bin/bash
set -e
REPO=/home/user/app
VENV=$REPO/venv

cd "$REPO"
# 1. Record current tag for rollback
CURRENT=$(git describe --tags --abbrev=0 2>/dev/null || git rev-parse HEAD)

# 2. Fetch + re-set sparse-checkout (in case set was broadened)
git fetch --tags --depth 1
# CRITICAL: filter to v* semver tags only — see pitfall below
NEW=$(git tag --sort=-creatordate | grep -E "^v[0-9]" | head -1)
git sparse-checkout set dir1 dir2 dir3   # idempotent re-set in cone mode
git checkout "$NEW"

# 3. Regenerate editable install MAPPING (sparse state changed)
pip install -e .

# 4. Update deps (lean install, skip heavy if not in requirements-lite.txt)
source "$VENV/bin/activate"
pip install --quiet -r requirements-lite.txt

# 5. Restart and health check
sudo systemctl restart app
sleep 30
if ! curl -sf http://localhost:8080/health > /dev/null; then
    echo "HEALTH CHECK FAILED, rolling back to $CURRENT"
    git checkout "$CURRENT"
    pip install -e .   # also re-run after rollback
    sudo systemctl restart app
    exit 1
fi
```

**CRITICAL pitfall — auto-pick target must filter to semver `v*` tags, not raw `head -1`.** A naive `git tag --sort=-creatordate | head -1` will often return a backup or merge tag (`backup/precopystrip-20260616-2058`, `merge-commit-backup`, `premerge-oh-god`, `clean-before-remerge`) instead of the latest release, because git sorts by **tag creation time**, not by the commit the tag points to. Internal tooling (CI snapshots, merge bots, manual `git tag backup/...` before rebases) creates these non-release tags constantly and they accumulate at the top of the creatordate-sorted list. Verified 2026-06-18 on hermes-agent: `git tag --sort=-creatordate | head -5` returned `backup/precopystrip-20260616-2058`, `backup/opentui-prestrip-20260616-1950`, then `v2026.6.5` — the script would have "upgraded" from `v2026.6.5` to a backup snapshot, not actually upgrading.

**Filter pattern** (always include in auto-pick):
```bash
NEW=$(git tag --sort=-creatordate | grep -E "^v[0-9]" | head -1)
```
Adjust the regex for your project's convention: `^v\d+\.\d+\.\d+$` for strict semver, `^release-` for CalVer-like, `^[0-9]` for plain version tags.

For the full production version of this script (dry-run mode, WS-connect health probe for Lark gateway, sparse-checkout backup-and-restore on rollback, import verification before restart), see `scripts/update-hermes.sh` in this skill — drop-in ready for `/root/hermes-scripts/update-hermes.sh` with `chmod 755`.

## Memory budget on constrained VPS (1 GB)

When adding a new Python service to a 1 GB VPS, plan:

| Service | Memory | Source |
|---|---|---|
| OS + base daemons | ~150 MB | Always |
| nginx + fail2ban | ~50 MB | Static |
| nanobot (Python WS) | ~200 MB | nanobot-specific |
| x-ui + xray (Go binary) | ~40 MB | x-ui-specific |
| new-api (Docker) | ~200 MB | Docker overhead |
| lark_oapi WS bot (Python) | ~175 MB | **verified 2026-06-18, idle process** |
| Hermes gateway + feishu platform | ~230 MB | **verified 2026-06-18, idle gateway** |
| **Remaining for new service** | **~50-100 MB** | tight, prefer e2-small (2 GB) |
| Swap | 2.5 GB | Buffer |

A lean Python service in this slot needs to stay under ~125 MB resident
on top of the existing stack. If you need a lark_oapi WS bot, plan for
~175 MB RSS by itself (Python interpreter + lark_oapi deps — aiohttp,
websockets, cryptography — are heavy, no lean alternative).

Verified runtime totals on instance-20260413-080555 (2026-06-18, before
Lark WS bot): used 575 MB / 954 MB. With one lark_oapi process added:
used 770 MB / 954 MB (81%). Tight but stable. Adding a SECOND lark_oapi
process would push to ~945 MB used → swap churn → OOMKill risk.
With Hermes gateway + feishu adapter (replaces standalone lark_adapter
+ adds agent core): used 648 MB / 954 MB (68%). Comfortable — Hermes
replaces nanobot's ~200 MB slot and consumes ~230 MB combined, similar
total footprint but with full agent capability.

## Verification checklist after deployment

- [ ] Disk: `df -h /home` — total < 80% of VPS capacity
- [ ] Memory: `free -h` — available > 100 MB at rest, swap used < 500 MB
- [ ] Process: `ps -ef | grep <service>` — running, expected PID, parent systemd
- [ ] Port: `ss -tlnp | grep <port>` — listening on expected port only
- [ ] Network: external `nc -w 1 -zv <public_ip> <port>` from another host — should be DROP/TIMEOUT for bypass ports, OPEN for public
- [ ] WS connection (Lark/Discord): test sending a message from external, verify received in log
- [ ] systemd: `systemctl status <service>` — active (running), no recent restart loops
- [ ] Editable install MAPPING: `python -c "import <top_pkg>"` for each MAPPING entry — no ModuleNotFoundError

## When sparse-checkout is wrong

Don't use sparse-checkout when:
- You actually need the full repo (e.g., building desktop app, docs site)
- The repo is small (< 100 MB) — overhead not worth it
- You can't enumerate the needed dirs upfront (sparse-checkout requires explicit list)

Use it when:
- Deploying to constrained VPS where disk matters
- You know exactly which dirs are runtime-needed
- You want predictable update behavior (no bloat re-pull)
