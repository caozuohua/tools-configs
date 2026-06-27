---
title: VPS health watchdog — single-SSH-roundtrip + section-marker pattern
source: 2026-06-18 setup on instance-20260413-080555 (e2-micro 1GB)
applies_to: any cron-driven health monitor for a GCP instance accessed via `gcloud compute ssh`
---

# VPS health watchdog

## The class of problem

You want a cron-scheduled check that:
1. Reads CPU / RAM / swap / disk / service status from a remote VPS
2. Alerts (delivered via Discord/Telegram/etc.) only when something is wrong, OR
   always emits a brief "OK" line so you know the cron is still running
3. Stays cheap (LLM-agent-free cron ticks burn no model tokens)

The naive approach — run `gcloud compute ssh` once per metric — takes 6× the
SSH round-trip latency. This reference documents the pattern that fits all three
requirements in one round trip.

## The pattern: one SSH, many sections, one parser

Pipe one bash command that emits a stream of `__LABEL__` markers, then parse
the output client-side into a dict.

### Remote command shape

```bash
echo "__MEM__"; free -m
echo "__DISK__"; df -h / | head -2
echo "__LOAD__"; uptime
echo "__FAILED__"; systemctl --failed --no-pager --plain 2>/dev/null
echo "__HERMES__"; systemctl is-active hermes-lite 2>&1; \
  systemctl show hermes-lite -p MainPID,MemoryCurrent 2>&1
echo "__LARK_LAST__"; journalctl -u hermes-lite --no-pager 2>/dev/null \
  | grep "msg-frontier-sg" | tail -1 | head -c 200
echo "__HERMES_ERRS__"; journalctl -u hermes-lite --since "30 min ago" \
  --no-pager 2>/dev/null | grep -ciE "error|disconnect|reconnect|warning" || true
echo "__DOCKER__"; docker ps -a --format "{{.Names}} {{.Status}}"
echo "__NEWAPI_TEST__"; curl -s -o /dev/null -w "%{http_code}" \
  http://127.0.0.1:3000/api/status 2>&1; echo
echo "__UPTIME_SEC__"; awk '{print int($1)}' /proc/uptime
```

### Two critical details

1. **Append `; echo` after any command whose output lacks a trailing newline** —
   notably `curl -w "%{http_code}"`. Without it, the next `echo "__NEXT__"`
   label is concatenated onto the previous section's content, and parsing
   silently collapses two sections into one.

2. **Drop `2>/dev/null` for commands whose stderr is diagnostic** — e.g.
   `docker ps` from a non-docker-group user emits the permission error to
   stderr, which then becomes the section content (empty stdout) instead of
   surfacing the real problem.

### Client-side parser

```python
def parse(out):
    sections, cur, buf = {}, None, []
    for line in out.splitlines():
        m = re.match(r"^__(\w+)__$", line)
        if m:
            if cur is not None:
                sections[cur] = "\n".join(buf).strip()
            cur = m.group(1); buf = []
        else:
            buf.append(line)
    if cur is not None:
        sections[cur] = "\n".join(buf).strip()
    return sections
```

## Threshold design for e2-micro (1GB RAM, 2.5GB swap)

Tuned thresholds for this class of instance — not generic numbers:

| Metric | Warn at | Why |
|---|---|---|
| swap_used_mb | **500 MB** | > 20% of 2.5GB total swap = real memory pressure (not transient startup). 200MB is too aggressive — startup peaks routinely hit 250-300MB and stay there. |
| mem_pct | **90%** | `free -m` "available" column is more accurate than "used", but a hard % ceiling catches leaks early. |
| disk_pct | **80%** | / disk. Log file growth, Docker image cache. |
| Lark WS last connect age | **don't alert on age alone** | Lark WebSocket is a *persistent* connection — once connected, no periodic reconnect happens. Alerting on "no reconnect in 30 min" fires constantly. Better signal: `journalctl --since "30 min ago" \| grep -ciE "error\|disconnect\|reconnect\|warning"`. |
| hermes ActiveState | not `active` | hard fail — gateway is down |
| new-api http code | `>= 500 or == 0` | 200 = ok, 401/403 = server alive but needs auth, anything 5xx = dead |
| `systemctl --failed` | any non-empty | skip header line ("UNIT LOAD ACTIVE SUB DESCRIPTION") and "0 loaded" summary; real failed units have a unit name followed by `failed failed ...` |

## Delivery pattern (cron with no_agent=True)

```python
# In cronjob create:
cronjob(action="create",
    schedule="*/30 * * * *",          # every 30 min
    no_agent=True,
    script="/home/caozuohua99/.local/bin/vps-watchdog.py",
    deliver="origin")                 # deliver stdout verbatim to your home channel
```

The script returns:
- **exit 0 + brief OK line** (`✅ VPS ... | ram ... | hermes=active ...`) — healthy
- **exit 1 + multi-line alert** (`🚨 VPS ...\n  ⚠️  ...\n  📊 ...`) — anomaly
- **exit 2 + error** (`🚨 VPS watchdog error ...`) — SSH timeout or gcloud failure

With `no_agent=True`, cron delivers stdout verbatim, so the user sees the same
message whether the script wrote "OK" or "alert". Empty stdout = silent (no
delivery) — useful for "alert only" pattern.

## Pitfalls

### `2>/dev/null` swallows real failures

If a non-docker-group user runs `docker ps`, the permission error goes to
stderr. With `2>/dev/null` you get empty stdout and conclude "no containers".
Without it you get the actual error in the section content and a clear signal.

### `awk '{print int($1)}' /proc/uptime` returns seconds correctly

Earlier version used `cat /proc/uptime \| awk '{print int($1)}'` — works but
extra cat. Direct awk is faster and more idiomatic.

### Don't alert on Lark WS "stale" — alert on actual disconnect logs

WS reconnect does not happen on a timer. Alerting on "no connect in N minutes"
fires constantly after the first 30 min. Use `journalctl --since` to count
recent `error|disconnect|reconnect|warning` lines instead.

### `systemctl is-active` output goes to stdout, not stderr

`systemctl is-active hermes-lite 2>&1` is necessary because some
implementations emit to stdout, some to stderr. The `2>&1` is cheap insurance.

### Cron with `notify_on_complete` is wrong for watchdog

Watchdogs are silent on success (or only print brief OK) and alerting on
failure. `notify_on_complete=true` fires every tick — wrong signal-to-noise.
Use `no_agent=True` so the script itself controls delivery via stdout/exit.

## Reference implementation

See `scripts/vps-watchdog.py` — parameterized (INST + ZONE via env vars with
defaults to the canonical `instance-20260413-080555` / `us-central1-c`).
Deploy with:

```bash
mkdir -p ~/.local/bin
# copy from skill scripts/ to bin, chmod +x
chmod +x ~/.local/bin/vps-watchdog.py
# test once
~/.local/bin/vps-watchdog.py
~/.local/bin/vps-watchdog.py --json   # full structured output for piping
```

## Related

- `references/hermes-redactor-workarounds.md` — workaround #5 (helper script
  indirection) for pushing credentialed files; same SSH-output philosophy
- `references/nanobot-deployment.md` — instance topology for context
- `SKILL.md` section "Resource Assessment Workflow" — ad-hoc health checks;
  this reference covers the *scheduled* counterpart