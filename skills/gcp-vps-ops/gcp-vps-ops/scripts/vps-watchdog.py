#!/usr/bin/env python3
"""
vps-watchdog.py — health check for a GCP instance via single SSH roundtrip.

Emits `__SECTION__` markers from a remote bash one-liner, parses them
client-side, applies class-level thresholds, and exits:
  0 + brief OK line  → healthy
  1 + multi-line alert → anomaly
  2 + error line       → SSH/gcloud failure

Designed for cron with no_agent=True: stdout is delivered verbatim, so
healthy ticks send "OK" messages and anomaly ticks send "🚨" alerts.
For silent-on-healthy, redirect to /dev/null in cron script wrapper.

Env (override defaults):
  VPS_INST  default: instance-20260413-080555
  VPS_ZONE  default: us-central1-c

Thresholds (tuned for e2-micro 1GB / 2.5GB swap):
  SWAP_WARN_MB=500, MEM_HIGH_PCT=90, DISK_WARN_PCT=80
  LARK_STALE alerts: ignore (use journal error count instead)
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

INST = os.environ.get("VPS_INST", "instance-20260413-080555")
ZONE = os.environ.get("VPS_ZONE", "us-central1-c")

SWAP_WARN_MB = 500
DISK_WARN_PCT = 80
MEM_HIGH_PCT = 90

REMOTE_CMD = r"""
echo "__MEM__"; free -m
echo "__DISK__"; df -h / | head -2
echo "__LOAD__"; uptime
echo "__FAILED__"; systemctl --failed --no-pager --plain 2>/dev/null
echo "__HERMES__"; systemctl is-active hermes-lite 2>&1; systemctl show hermes-lite -p MainPID,MemoryCurrent 2>&1
echo "__LARK_LAST__"; journalctl -u hermes-lite --no-pager 2>/dev/null | grep "msg-frontier-sg" | tail -1 | head -c 200
echo "__HERMES_ERRS__"; journalctl -u hermes-lite --since "30 min ago" --no-pager 2>/dev/null | grep -ciE "error|disconnect|reconnect|warning" || true
echo "__DOCKER__"; docker ps -a --format "{{.Names}} {{.Status}}"
echo "__NEWAPI_TEST__"; curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3000/api/status 2>&1; echo
echo "__UPTIME_SEC__"; awk '{print int($1)}' /proc/uptime
"""

def fetch():
    try:
        r = subprocess.run(
            ["gcloud", "compute", "ssh", INST, f"--zone={ZONE}",
             f"--command={REMOTE_CMD}"],
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        return None, "ssh timeout (60s)"
    if r.returncode != 0:
        return None, f"ssh exit {r.returncode}: {r.stderr.strip()[:200]}"
    return r.stdout, None

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

def mem_stats(s):
    out = {"mem_total_mb": 0, "mem_used_mb": 0, "mem_avail_mb": 0,
           "swap_used_mb": 0, "mem_pct": 0}
    for line in s.splitlines():
        if line.startswith("Mem:"):
            parts = line.split()
            out["mem_total_mb"] = int(parts[1])
            out["mem_used_mb"] = int(parts[2])
            out["mem_avail_mb"] = int(parts[6]) if len(parts) > 6 else int(parts[3])
        elif line.startswith("Swap:"):
            parts = line.split()
            out["swap_used_mb"] = int(parts[2])
    if out["mem_total_mb"]:
        out["mem_pct"] = round(100 * out["mem_used_mb"] / out["mem_total_mb"], 1)
    return out

def disk_stats(s):
    out = {"disk_pct": 0, "disk_free_gb": 0}
    lines = [l for l in s.splitlines() if l.startswith("/")]
    if lines:
        parts = lines[0].split()
        try:
            out["disk_pct"] = int(parts[4].rstrip("%"))
        except (ValueError, IndexError):
            pass
        free_str = parts[3]
        m = re.match(r"(\d+(?:\.\d+)?)([KMGT])", free_str)
        if m:
            num, unit = float(m.group(1)), m.group(2)
            mult = {"K": 1/1024/1024, "M": 1/1024, "G": 1, "T": 1024}.get(unit, 1)
            out["disk_free_gb"] = round(num * mult, 1)
    return out

def load_avg(s):
    m = re.search(r"load average:\s*([\d.]+)", s)
    return float(m.group(1)) if m else 0.0

def hermes_status(s):
    lines = s.splitlines()
    active = lines[0].strip() if lines else "unknown"
    pid = mem = None
    for line in lines[1:]:
        if line.startswith("MainPID="):
            pid = line.split("=", 1)[1].strip()
        elif line.startswith("MemoryCurrent="):
            val = line.split("=", 1)[1].strip()
            if val and val != "[not set]":
                try: mem = int(val) // (1024 * 1024)
                except ValueError: pass
    return {"active": active, "pid": pid, "mem_mb": mem}

def lark_age_seconds(s):
    line = s.strip()
    if not line: return None
    m = re.search(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
    if not m: return None
    try:
        ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return int((datetime.now(timezone.utc) - ts).total_seconds())
    except ValueError:
        return None

def docker_status(s):
    out = []
    for line in s.splitlines():
        if not line.strip(): continue
        parts = line.split(maxsplit=1)
        if len(parts) >= 2:
            out.append({"name": parts[0], "status": parts[1]})
    return out

def failed_units_parse(s):
    out = []
    for line in s.splitlines():
        line = line.strip()
        if not line or line.startswith("UNIT") or line.startswith("0 loaded"):
            continue
        parts = line.split(None, 4)
        if len(parts) >= 4 and parts[2] == "failed":
            out.append(f"{parts[0]}: {parts[4] if len(parts) > 4 else 'failed'}")
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    raw, err = fetch()
    if err:
        ts = datetime.now(timezone.utc).strftime("%H:%M UTC")
        print(f"🚨 VPS watchdog error {ts}: {err}")
        sys.exit(2)

    s = parse(raw)
    mem = mem_stats(s.get("MEM", ""))
    disk = disk_stats(s.get("DISK", ""))
    load = load_avg(s.get("LOAD", ""))
    hermes = hermes_status(s.get("HERMES", ""))
    lark_age = lark_age_seconds(s.get("LARK_LAST", ""))
    hermes_errs = int(s.get("HERMES_ERRS", "0") or "0")
    docker = docker_status(s.get("DOCKER", ""))
    newapi = s.get("NEWAPI_TEST", "?").strip().split()[0]
    uptime_s = int(s.get("UPTIME_SEC", "0") or "0")
    failed_units = failed_units_parse(s.get("FAILED", ""))

    alerts = []
    if mem["swap_used_mb"] > SWAP_WARN_MB:
        alerts.append(f"swap={mem['swap_used_mb']}M > {SWAP_WARN_MB}M")
    if mem["mem_pct"] > MEM_HIGH_PCT:
        alerts.append(f"mem={mem['mem_pct']}% > {MEM_HIGH_PCT}%")
    if disk["disk_pct"] > DISK_WARN_PCT:
        alerts.append(f"disk={disk['disk_pct']}% > {DISK_WARN_PCT}%")
    if hermes["active"] != "active":
        alerts.append(f"hermes-lite: {hermes['active']}")
    if hermes_errs > 0:
        alerts.append(f"hermes-lite log: {hermes_errs} error/warn lines in 30min")
    if failed_units:
        alerts.append(f"failed units: {'; '.join(failed_units[:3])}")
    if newapi and newapi.isdigit():
        code = int(newapi)
        if code >= 500 or code == 0:
            alerts.append(f"new-api http {code}")

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if args.json:
        print(json.dumps({
            "ts": ts, "uptime_s": uptime_s,
            "mem": mem, "disk": disk, "load_1m": load,
            "hermes": hermes, "lark_last_age_s": lark_age,
            "hermes_errs_30min": hermes_errs,
            "docker": docker, "newapi_http": newapi,
            "failed_units": failed_units, "alerts": alerts,
        }, indent=2, ensure_ascii=False))
        sys.exit(1 if alerts else 0)

    hermes_str = (f"hermes={hermes['active']} pid={hermes['pid'] or '-'} "
                  f"mem={hermes['mem_mb'] or '-'}M lark_last={lark_age // 60 if lark_age is not None else '?'}m")
    base = (f"ram {mem['mem_used_mb']}/{mem['mem_total_mb']}M "
            f"swap {mem['swap_used_mb']}M "
            f"disk {disk['disk_pct']}% ({disk['disk_free_gb']}G free) "
            f"load {load} up {uptime_s // 3600}h")

    if alerts:
        print(f"🚨 VPS {ts}\n  ⚠️  {'; '.join(alerts)}\n  📊 {base}\n  🔌 {hermes_str}\n  🐳 docker: {', '.join(d['name'] for d in docker) or '-'}")
        sys.exit(1)

    print(f"✅ VPS {ts} | {base} | {hermes_str}")
    sys.exit(0)

if __name__ == "__main__":
    main()