#!/usr/bin/env bash
# Restart the retail backend the way the launcher runs it.
#
# The failure this prevents: a backend started by hand, without the launcher's
# environment, drops CORS_ORIGINS. curl keeps working, so the backend looks
# healthy — while the browser refuses every preflight and the whole application
# reads "Cannot reach the CreditProbe backend". Ninety minutes were spent
# reading application code for a defect that was in how the server was started.
set -euo pipefail
cd "$(dirname "$0")/../.."
set -a; . ./.env.retail; set +a
LOG="${1:-/tmp/retail-backend.log}"

if [ -f var/retail/backend.pid ]; then
  PID="$(cat var/retail/backend.pid)"
  if [ -d "/proc/$PID" ] && tr '\0' ' ' < "/proc/$PID/cmdline" | grep -q "uvicorn backend.api.main:app"; then
    kill "$PID"
    for _ in $(seq 1 20); do [ -d "/proc/$PID" ] || break; sleep 1; done
    # Confirmed, not assumed. uvicorn can hang in "Waiting for background
    # tasks to complete", and starting a second server on the same port then
    # fails to bind — which reads on screen as "the backend is unreachable".
    if [ -d "/proc/$PID" ]; then
      echo "backend $PID did not stop in 20s; ending it" >&2
      kill -9 "$PID" 2>/dev/null || true
      for _ in 1 2 3 4 5; do [ -d "/proc/$PID" ] || break; sleep 1; done
    fi
  fi
fi

mkdir -p var/retail
nohup .venv/bin/python -m uvicorn backend.api.main:app \
  --host 127.0.0.1 --port "${API_PORT}" > "$LOG" 2>&1 &
echo $! > var/retail/backend.pid

for _ in $(seq 1 40); do
  if curl -fsS "http://localhost:${API_PORT}/api/v1/health" > /dev/null 2>&1; then
    echo "backend ready on ${API_PORT} (pid $(cat var/retail/backend.pid))"
    exit 0
  fi
  sleep 1
done
echo "backend did not answer /api/v1/health" >&2
tail -20 "$LOG" >&2
exit 1
