#!/usr/bin/env bash
set -euo pipefail

BASE="${HERMES_HOME:-$HOME/.hermes-lite}"

echo "== hermes-lite service =="
systemctl show hermes-lite -p ActiveState,SubState,NRestarts,MainPID || true
systemctl status hermes-lite --no-pager --lines=12 || true

echo "== config =="
if [ -f "$BASE/config.yaml" ]; then
  if [ -x "$BASE/venv/bin/python3" ]; then
    "$BASE/venv/bin/python3" - <<'PY'
from pathlib import Path
import sys

path = Path.home() / ".hermes-lite" / "config.yaml"
try:
    import yaml
except ModuleNotFoundError:
    print("yaml_check=skipped_no_pyyaml")
    sys.exit(0)

yaml.safe_load(path.read_text())
print("yaml_check=ok")
PY
  fi
  stat -c 'config_perm=%a %U:%G %n' "$BASE/config.yaml"
else
  echo "config=missing"
fi

echo "== process =="
pgrep -af "hermes gateway run" || true

echo "== resources =="
df -h "$BASE" | tail -1 | awk '{print "disk_free=" $4 " total=" $2 " used=" $5}'
free -h | awk '/^Mem:/ {print "mem_available=" $7 " total=" $2}'

echo "== state db =="
if [ -f "$BASE/workspace/state.db" ] && command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$BASE/workspace/state.db" "PRAGMA integrity_check;"
else
  echo "state_db_check=skipped"
fi

echo "== new-api =="
docker ps --filter name=new-api --format 'container={{.Names}} status={{.Status}} ports={{.Ports}}' || true
curl -sk -o /dev/null -w 'new_api_local_status_http=%{http_code}\n' --max-time 3 http://127.0.0.1:3000/api/status || true

echo "== x-ui =="
if sudo -n test -f /etc/x-ui/x-ui.db 2>/dev/null; then
  sudo -n sqlite3 /etc/x-ui/x-ui.db "SELECT 'webBasePath_len=' || length(value) || ' leading=' || substr(value,1,1) FROM settings WHERE key='webBasePath';" || true
  curl -sk -o /dev/null -w 'xui_root_http=%{http_code}\n' --max-time 3 http://127.0.0.1:50404/ || true
else
  echo "xui_db=missing_or_no_sudo"
fi

echo "== recent warnings =="
if [ -f "$BASE/logs/gateway.log" ]; then
  grep -Eai 'error|fail|fatal|traceback|exception|disconnect' "$BASE/logs/gateway.log" | tail -20 || true
fi
