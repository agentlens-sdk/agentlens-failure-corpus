#!/usr/bin/env bash
# Nightly entrypoint for cron. Single-instance, self-contained, quiet on success.
set -euo pipefail
cd "$(dirname "$0")"
export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:?set in ~/.corpus.env}"

# Interpreter must be absolute: cron's PATH does not have the venv, and may not have `python`.
PY="$(pwd)/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

mkdir -p logs
LOG="logs/$(date +%F).log"

# Single instance. mkdir is atomic on macOS and Linux; flock is Linux-only and was silently fatal here.
LOCK="${TMPDIR:-/tmp}/corpus.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  # Take over a lock left behind by a crashed run (episodes are capped well under 6h).
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +360 2>/dev/null)" ]; then
    rmdir "$LOCK" 2>/dev/null || true
    mkdir "$LOCK" 2>/dev/null || { echo "$(date -u +%FT%TZ) lock busy, exiting" >> "$LOG"; exit 0; }
  else
    echo "$(date -u +%FT%TZ) another run holds the lock, exiting" >> "$LOG"
    exit 0
  fi
fi
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

"$PY" -m corpus.scheduler >> "$LOG" 2>&1

# Weekly hygiene (Sunday).
if [ "$(date +%u)" = "7" ]; then
  command -v docker >/dev/null && docker system prune -af --volumes >/dev/null 2>&1 || true
  find logs -name '*.log' -mtime +30 -delete 2>/dev/null || true
fi
