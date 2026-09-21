#!/usr/bin/env sh
PORT="${1:-${PORT:-4317}}"

if command -v lsof >/dev/null 2>&1; then
  PIDS="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN)"
  if [ -n "$PIDS" ]; then
    kill $PIDS
    echo "Port $PORT released."
    exit 0
  fi
fi

echo "Port $PORT is not listening."
