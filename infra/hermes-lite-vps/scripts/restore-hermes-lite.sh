#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: restore-hermes-lite.sh /path/to/hermes-lite-baseline.tar.gz" >&2
  exit 2
fi

ARCHIVE="$1"
BASE="${HERMES_HOME:-$HOME/.hermes-lite}"

if [ ! -f "$ARCHIVE" ]; then
  echo "archive not found: $ARCHIVE" >&2
  exit 2
fi

if [ -f "$ARCHIVE.sha256" ]; then
  sha256sum -c "$ARCHIVE.sha256"
fi

mkdir -p "$BASE"
chmod 700 "$BASE"

echo "Restoring to $BASE"
tar -C "$BASE" -xzf "$ARCHIVE"

[ -f "$BASE/.env" ] && chmod 600 "$BASE/.env"
[ -f "$BASE/.env.lark" ] && chmod 600 "$BASE/.env.lark"
[ -f "$BASE/config.yaml" ] && chmod 600 "$BASE/config.yaml"

echo "Restore complete. Restart hermes-lite after reviewing restored config."
