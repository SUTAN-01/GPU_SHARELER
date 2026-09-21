#!/usr/bin/env sh
PORT="${1:-${PORT:-4317}}"

if command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "Port $PORT is already in use. The service may already be running at http://localhost:$PORT"
  echo "Use: ./start.sh 4318"
  exit 0
fi

if command -v python3 >/dev/null 2>&1; then
  PORT="$PORT" python3 "$(dirname "$0")/server.py"
elif command -v python >/dev/null 2>&1; then
  PORT="$PORT" python "$(dirname "$0")/server.py"
else
  echo "Python 3.9+ is required."
  exit 1
fi
