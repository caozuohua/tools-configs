#!/bin/bash
# monitor-nanobot.sh — quick health snapshot for nanobot on a GCP VPS
# Usage: gcloud compute ssh <instance> --zone=<zone> --command='bash /tmp/monitor-nanobot.sh'
#
# Reads /proc, journal, and ss without sudo. Works for any nanobot-like
# Python service (process name and unit name are parameters at the top).
#
# Output: human-readable health snapshot — process, threads, memory,
# recent activity, network, dream cron state, error counts.

# === CONFIGURE THESE ===
PROCESS_NAME="nanobot gateway"   # matches against ps -ef cmdline
SYSTEMD_UNIT="nanobot.service"
LOOKBACK_MIN=30                   # how far back to scan journal
SINCE_FLAG="${LOOKBACK_MIN} min ago"

# === HEAD ===
echo "=================================================="
echo "  nanobot Health Snapshot — $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "=================================================="
echo

# === PROCESS STATE ===
echo "─── PROCESS ───"
PID=$(pgrep -f "$PROCESS_NAME" | head -1)
if [ -z "$PID" ]; then
    echo "  ✗ no process found matching '$PROCESS_NAME'"
    exit 1
fi

START_TIME=$(ps -o lstart= -p "$PID" 2>/dev/null | xargs)
RSS_MB=$(awk '/VmRSS/{print int($2/1024)}' /proc/$PID/status)
VSZ_MB=$(awk '/VmSize/{print int($2/1024)}' /proc/$PID/status)
THREADS=$(awk '/Threads/{print $2}' /proc/$PID/status)
STATE=$(awk '/State/{print $2, $3}' /proc/$PID/status)

echo "  PID:      $PID"
echo "  Started:  $START_TIME"
echo "  State:    $STATE"
echo "  RSS:      ${RSS_MB} MB"
echo "  VSZ:      ${VSZ_MB} MB"
echo "  Threads:  $THREADS"
echo

# === SYSTEMD HEALTH (no sudo) ===
echo "─── SYSTEMD ───"
systemctl show "$SYSTEMD_UNIT" --property=ActiveState,SubState,MemoryCurrent,MemoryHigh,MemoryMax,TasksCurrent,NRestarts,ExecMainStartTimestamp 2>/dev/null | sed 's/^/  /'
echo

# === MEMORY TREND ===
echo "─── MEMORY ───"
free -h | head -2 | sed 's/^/  /'
echo

# === THREAD STATE ===
echo "─── THREADS ───"
for t in /proc/$PID/task/*; do
    tid=$(basename "$t")
    state=$(awk '{print $3}' "$t/stat" 2>/dev/null)
    utime=$(awk '{print int($14/100)}' "$t/stat" 2>/dev/null)
    echo "  tid $tid: state=$state utime=${utime}ms"
done
echo

# === RECENT ACTIVITY (from journal) ===
echo "─── JOURNAL (last ${LOOKBACK_MIN} min) ───"
# Count events by type
PROCESSED=$(journalctl -u "$SYSTEMD_UNIT" --no-pager --since "$SINCE_FLAG" 2>/dev/null | grep -c "Processing message")
TOOL_CALLS=$(journalctl -u "$SYSTEMD_UNIT" --no-pager --since "$SINCE_FLAG" 2>/dev/null | grep -c "Tool call")
RESPONSES=$(journalctl -u "$SYSTEMD_UNIT" --no-pager --since "$SINCE_FLAG" 2>/dev/null | grep -c "Response to")
ERRORS=$(journalctl -u "$SYSTEMD_UNIT" --no-pager --since "$SINCE_FLAG" 2>/dev/null | grep -c "ERROR")
WARNINGS=$(journalctl -u "$SYSTEMD_UNIT" --no-pager --since "$SINCE_FLAG" 2>/dev/null | grep -c "WARNING")
echo "  processed: $PROCESSED  tool_calls: $TOOL_CALLS  responses: $RESPONSES"
echo "  errors:    $ERRORS     warnings:   $WARNINGS"
echo

# === LARK / EXTERNAL CONN ===
echo "─── LIVE CONNECTIONS (uid=$PID's user) ───"
USER_UID=$(awk '/^Uid:/{print $2}' /proc/$PID/status)
ESTABLISHED=$(cat /proc/net/tcp /proc/net/tcp6 2>/dev/null | awk -v u="$USER_UID" '$4=="01" && $10==u {print $2, "->", $3}' | head -5)
if [ -n "$ESTABLISHED" ]; then
    echo "$ESTABLISHED" | sed 's/^/  /'
else
    echo "  (no ESTABLISHED connections for uid $USER_UID)"
fi
echo

# === DREAM CRON (if applicable) ===
echo "─── DREAM CRON (last 4h) ───"
journalctl -u "$SYSTEMD_UNIT" --no-pager --since "4 hours ago" 2>/dev/null | grep -E "Dream.*completed|executing job|Cursor advanced" | tail -5 | sed 's/^/  /'
echo

# === 429 / RESOURCE EXHAUSTED COUNT ===
echo "─── API ERRORS (last 4h) ───"
COUNT_429=$(journalctl -u "$SYSTEMD_UNIT" --no-pager --since "4 hours ago" 2>/dev/null | grep -c "429\|RESOURCE_EXHAUSTED")
echo "  429 / resource_exhausted: $COUNT_429"
echo

# === QUICK VERDICT ===
echo "─── VERDICT ───"
if [ -n "$PID" ] && [ "$ERRORS" -eq 0 ]; then
    echo "  ✓ healthy (process up, no errors in last ${LOOKBACK_MIN}m)"
elif [ -n "$PID" ] && [ "$ERRORS" -gt 0 ]; then
    echo "  ⚠ degraded (process up, $ERRORS errors in last ${LOOKBACK_MIN}m)"
else
    echo "  ✗ not running"
fi

# === DIFF WITH PREVIOUS (optional) ===
# If you've been calling this script repeatedly, you can diff outputs
# to spot regressions. Suggested:
#   gcloud compute ssh ... --command='bash /tmp/monitor.sh' > /tmp/snap-$(date +%H%M).txt
#   diff /tmp/snap-0900.txt /tmp/snap-1000.txt
