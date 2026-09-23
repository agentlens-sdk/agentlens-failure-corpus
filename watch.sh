#!/usr/bin/env bash
# Serve the repo root so site/live.html can read data/runstate.json, and print the URL.
# Read-only and local: it opens no browser, touches no data, and is safe to start before, during or
# after a run. Ctrl-C to stop. PORT=... to move it (8766 is AgentLens itself, so the default is 8777).
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8777}"
PY="$(pwd)/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

echo "watching $(pwd)"
echo "  live run: http://127.0.0.1:$PORT/site/live.html"
echo "  dashboard: http://127.0.0.1:$PORT/site/index.html"
echo

# --bind 127.0.0.1: this serves the whole repo, including the ledger. It does not leave the machine.
exec "$PY" -m http.server "$PORT" --bind 127.0.0.1
