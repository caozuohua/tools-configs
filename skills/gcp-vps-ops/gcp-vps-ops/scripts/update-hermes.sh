#!/usr/bin/env bash
# update-hermes.sh — Strategy C: manual trigger + atomic rollback
#
# Updates a Hermes Lite deployment (sparse-cloned hermes-agent + lean venv
# + systemd-managed gateway) to the latest v* tag, with WS health check
# + automatic rollback on failure.
#
# Usage:
#   sudo /root/hermes-scripts/update-hermes.sh           # update to latest v* tag
#   sudo /root/hermes-scripts/update-hermes.sh v0.16.1   # update to specific tag
#   sudo /root/hermes-scripts/update-hermes.sh --dry-run # show plan, no changes
#
# Prerequisites:
#   - Hermes deployed via sparse-checkout cone mode (see sparse-checkout-and-lean-venv.md)
#   - Service managed by systemd (default unit: hermes-lite.service)
#   - Caller has sudo (for systemctl restart + pip install + git checkout)
#   - Log file: /var/log/hermes-update.log (auto-created)
#
# Verified 2026-06-18 against:
#   - instance-20260413-080555 (e2-micro 1GB VPS)
#   - Hermes-agent v2026.6.5 (sparse-cloned, 7 dirs + cone mode)
#   - systemd unit /etc/systemd/system/hermes-lite.service
#   - WebSocket Lark channel as health probe (logs "connected to wss://...")

set -euo pipefail

# === CONFIG (edit if your layout differs) ===
HERMES_DIR="/home/caozuohua99/.hermes-lite/hermes-agent"
HERMES_USER="caozuohua99"
SYSTEMD_UNIT="hermes-lite.service"
HEALTH_TIMEOUT=30   # seconds to wait for WS reconnect after restart
LOG="/var/log/hermes-update.log"

# === HELPERS ===
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG" >&2; }
fail() { log "FAIL: $*"; exit 1; }

# === ARGS ===
DRY_RUN=0
TARGET_TAG="${1:-}"
[ "${1:-}" = "--dry-run" ] && { DRY_RUN=1; TARGET_TAG=""; }

# === PRE-FLIGHT ===
[ -d "$HERMES_DIR/.git" ] || fail "Not a git repo: $HERMES_DIR"
cd "$HERMES_DIR"

# Backup current sparse-checkout config (defensive — usually unchanged)
SPARSE_BACKUP="$(mktemp -d)/sparse-checkout.before"
cp .git/info/sparse-checkout "$SPARSE_BACKUP/" 2>/dev/null || true

# Capture current state for rollback
CURRENT_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "unknown")
CURRENT_SHA=$(git rev-parse --short HEAD)
log "Current: tag=$CURRENT_TAG sha=$CURRENT_SHA"

# Fetch all tags (shallow — depth 1 is enough)
log "Fetching tags..."
git fetch --tags --depth 1 2>&1 | tee -a "$LOG" > /dev/null

# === PICK TARGET ===
# CRITICAL: filter to v* semver tags only. Tags like backup/* or premerge-*
# (created by internal CI or merge tooling) sort NEWER than real releases
# by `--sort=-creatordate` and would trigger a bogus "update" to a backup
# snapshot. Verify: `git tag --sort=-creatordate | head -10` — if you see
# backup/* or premerge-* at the top, this filter is essential.
if [ -z "$TARGET_TAG" ]; then
    TARGET_TAG=$(git tag --sort=-creatordate | grep -E "^v[0-9]" | head -1)
fi
[ -n "$TARGET_TAG" ] || fail "No v* target tag found"
if [ "$TARGET_TAG" = "$CURRENT_TAG" ]; then
    log "Already on $TARGET_TAG, nothing to do"
    exit 0
fi
log "Target: tag=$TARGET_TAG"

# Verify target exists
git rev-parse "refs/tags/$TARGET_TAG" >/dev/null 2>&1 \
    || fail "Tag $TARGET_TAG does not exist"

if [ "$DRY_RUN" = 1 ]; then
    log "DRY RUN — would update $CURRENT_TAG -> $TARGET_TAG (no changes made)"
    log "Sparse-checkout config (would re-assert):"
    cat .git/info/sparse-checkout | sed 's/^/    /'
    exit 0
fi

# === RE-ASSERT SPARSE-CHECKOUT ===
# If anyone ran `sparse-checkout add` (non-cone mode quirk — it disables
# cone mode), the dir set may have leaked. Re-assert cone mode and the
# exact dir list before checkout to guarantee a clean sparse state.
log "Re-asserting sparse-checkout (cone mode)..."
git sparse-checkout init --cone 2>&1 | tee -a "$LOG" > /dev/null || true
git sparse-checkout set agent cron hermes_cli plugins providers scripts gateway tools \
    2>&1 | tee -a "$LOG" > /dev/null

# === CHECKOUT NEW TAG ===
log "Checking out $TARGET_TAG..."
git checkout "$TARGET_TAG" 2>&1 | tee -a "$LOG" > /dev/null \
    || fail "git checkout failed"
NEW_SHA=$(git rev-parse --short HEAD)
log "New: sha=$NEW_SHA"

# === REFRESH EDITABLE INSTALL ===
# The MAPPING in __editable___hermes_agent_X_X_X_finder.py was generated
# for the OLD sparse state. After sparse-checkout changes, MAPPING may
# reference missing paths or miss new ones. Re-run to regenerate.
log "Refreshing pip install -e . (regenerates editable MAPPING)..."
sudo -u "$HERMES_USER" /home/caozuohua99/.hermes-lite/venv/bin/pip install -e . \
    2>&1 | tee -a "$LOG" | tail -3

# Verify imports before restart (fail fast if install broke something)
log "Verifying imports..."
sudo -u "$HERMES_USER" /home/caozuohua99/.hermes-lite/venv/bin/python -c "
import hermes_constants
from gateway.platforms.feishu import FEISHU_AVAILABLE
assert FEISHU_AVAILABLE, 'feishu not available'
print('imports OK')
" 2>&1 | tee -a "$LOG" || fail "Import verification failed"

# === RESTART ===
log "Restarting $SYSTEMD_UNIT..."
systemctl restart "$SYSTEMD_UNIT"
sleep 3

# === HEALTH CHECK ===
# For Lark channel: WS reconnect shows in journal as
# "connected to wss://msg-frontier-..." within ~15-20s of startup.
# Adjust HEALTH_TIMEOUT if your platform reconnects slower.
log "Health check (timeout=${HEALTH_TIMEOUT}s, probing for WS reconnect)..."
HEALTH_OK=0
for i in $(seq 1 "$HEALTH_TIMEOUT"); do
    if ! systemctl is-active --quiet "$SYSTEMD_UNIT"; then
        log "  attempt $i: service not active"
        sleep 1
        continue
    fi
    if journalctl -u "$SYSTEMD_UNIT" --since "30s ago" --no-pager 2>/dev/null \
        | grep -q "connected to wss://"; then
        HEALTH_OK=1
        log "  attempt $i: WS reconnected ✓"
        break
    fi
    log "  attempt $i: WS not yet connected"
    sleep 1
done

# === ROLLBACK ===
if [ "$HEALTH_OK" != 1 ]; then
    log "HEALTH CHECK FAILED — rolling back to $CURRENT_TAG"
    git checkout "$CURRENT_TAG" 2>&1 | tee -a "$LOG" > /dev/null
    # Restore exact pre-update sparse-checkout config (defensive)
    [ -f "$SPARSE_BACKUP/sparse-checkout.before" ] \
        && cp "$SPARSE_BACKUP/sparse-checkout.before" .git/info/sparse-checkout
    sudo -u "$HERMES_USER" /home/caozuohua99/.hermes-lite/venv/bin/pip install -e . \
        2>&1 | tee -a "$LOG" | tail -3
    systemctl restart "$SYSTEMD_UNIT"
    sleep 5
    if systemctl is-active --quiet "$SYSTEMD_UNIT"; then
        log "Rollback succeeded — gateway active on $CURRENT_TAG"
    else
        log "Rollback DEGRADED — gateway NOT active. Investigate manually:"
        log "  journalctl -u $SYSTEMD_UNIT --since '5 min ago'"
    fi
    fail "Health check failed; rolled back to $CURRENT_TAG"
fi

log "SUCCESS: $CURRENT_TAG ($CURRENT_SHA) -> $TARGET_TAG ($NEW_SHA)"
log "Sparse-checkout config (preserved):"
cat .git/info/sparse-checkout | sed 's/^/    /'
