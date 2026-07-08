#!/usr/bin/env bash
set -euo pipefail

BASE="${HERMES_HOME:-$HOME/.hermes-lite}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="$BASE/backups"
STAGE="$(mktemp -d)"

cleanup() {
  rm -rf "$STAGE"
}
trap cleanup EXIT

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

mkdir -p "$STAGE/workspace"

if [ -f "$BASE/workspace/state.db" ] && command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$BASE/workspace/state.db" "PRAGMA integrity_check;"
  sqlite3 "$BASE/workspace/state.db" ".backup '$STAGE/workspace/state.db'"
elif [ -f "$BASE/workspace/state.db" ]; then
  cp -p "$BASE/workspace/state.db" "$STAGE/workspace/state.db"
fi

[ -f "$BASE/config.yaml" ] && cp -p "$BASE/config.yaml" "$STAGE/config.yaml"
[ -f "$BASE/.env" ] && cp -p "$BASE/.env" "$STAGE/.env"
[ -f "$BASE/.env.lark" ] && cp -p "$BASE/.env.lark" "$STAGE/.env.lark"
[ -f "$BASE/tavily_credentials.json" ] && cp -p "$BASE/tavily_credentials.json" "$STAGE/tavily_credentials.json"
[ -d "$BASE/skills" ] && cp -a "$BASE/skills" "$STAGE/skills"

ARCHIVE="$BACKUP_DIR/hermes-lite-baseline-$TS.tar.gz"
tar -C "$STAGE" -czf "$ARCHIVE" .
chmod 600 "$ARCHIVE"
sha256sum "$ARCHIVE" > "$ARCHIVE.sha256"
chmod 600 "$ARCHIVE.sha256"

printf 'backup=%s\n' "$ARCHIVE"
printf 'sha256=%s\n' "$(awk '{print $1}' "$ARCHIVE.sha256")"
