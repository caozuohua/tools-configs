#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: verify-public-ports.sh PUBLIC_IP_OR_HOST" >&2
  exit 2
fi

HOST="$1"

check_port() {
  local port="$1"
  local expected="$2"

  if timeout 3 bash -c "cat < /dev/null > /dev/tcp/$HOST/$port" 2>/dev/null; then
    actual="open"
  else
    actual="closed"
  fi

  printf 'port=%s actual=%s expected=%s\n' "$port" "$actual" "$expected"

  if [ "$actual" != "$expected" ]; then
    return 1
  fi
}

status=0
check_port 22 open || status=1
check_port 80 open || status=1
check_port 443 open || status=1
check_port 3000 closed || status=1
check_port 50404 closed || status=1
check_port 44301 closed || status=1

exit "$status"
