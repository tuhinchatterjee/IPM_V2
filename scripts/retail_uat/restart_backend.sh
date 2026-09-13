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
# An API_PORT given on the command line wins over the one in the file, so a
# second instance can be started somewhere else — and so the regression that
# covers this script can exercise it without stopping the real backend.
PORT_OVERRIDE="${API_PORT:-}"
set -a; . ./.env.retail; set +a
if [ -n "$PORT_OVERRIDE" ]; then API_PORT="$PORT_OVERRIDE"; fi
LOG="${1:-/tmp/retail-backend.log}"

# Is this process alive? `/proc` was used here and macOS does not have one,
# so on a Mac every check below was false, the old backend was never killed,
# the new one could not bind the port and died, and the health check below
# passed because the OLD server answered it. The script then printed "backend
# ready" while the machine kept serving whatever code it had started with:
# no /retail/ews routes, and a governed catalogue cached from before the
# Early Warning Score domain was built. `kill -0` and `ps` work on both.
alive() { kill -0 "$1" 2>/dev/null; }
is_our_backend() {
  ps -o command= -p "$1" 2>/dev/null | grep -q "uvicorn backend.api.main:app"
}

stop_pid() {
  local PID="$1"
  alive "$PID" || return 0
  is_our_backend "$PID" || return 0
  kill "$PID" 2>/dev/null || true
  for _ in $(seq 1 20); do alive "$PID" || break; sleep 1; done
  # Confirmed, not assumed. uvicorn can hang in "Waiting for background
  # tasks to complete", and starting a second server on the same port then
  # fails to bind — which reads on screen as "the backend is unreachable".
  if alive "$PID"; then
    echo "backend $PID did not stop in 20s; ending it" >&2
    kill -9 "$PID" 2>/dev/null || true
    for _ in 1 2 3 4 5; do alive "$PID" || break; sleep 1; done
  fi
}

# The recorded pid is recorded PER PORT. It was one file for every port, so
# starting a second instance somewhere else stopped the first one — which is
# how the regression for this script took the real backend down with it.
mkdir -p var/retail
PIDFILE="var/retail/backend.${API_PORT}.pid"
if [ -f var/retail/backend.pid ] && [ ! -f "$PIDFILE" ] \
   && [ "$API_PORT" = "${PORT_OVERRIDE:-$API_PORT}" ] \
   && [ -z "$PORT_OVERRIDE" ]; then
  # An installation started before this file was named after its port.
  mv var/retail/backend.pid "$PIDFILE"
fi
if [ -f "$PIDFILE" ]; then
  stop_pid "$(cat "$PIDFILE")"
fi

# A backend this script did not record — started by the launcher, by hand, or
# by an earlier checkout — still holds the port, and that is the process the
# Mac kept serving. Anything on API_PORT that is one of ours is stopped too.
if command -v lsof > /dev/null 2>&1; then
  for PID in $(lsof -ti "tcp:${API_PORT}" -sTCP:LISTEN 2>/dev/null || true); do
    stop_pid "$PID"
  done
fi

# The port has to be free before the new server starts, or it exits on bind
# and the old one answers in its place.
for _ in $(seq 1 20); do
  curl -fsS "http://localhost:${API_PORT}/api/v1/health" > /dev/null 2>&1 || break
  sleep 1
done
if curl -fsS "http://localhost:${API_PORT}/api/v1/health" > /dev/null 2>&1; then
  echo "something is still serving port ${API_PORT} and this script could not" >&2
  echo "stop it. Starting another server would silently leave the old one in" >&2
  echo "place. Stop it by hand and run this again." >&2
  if command -v lsof > /dev/null 2>&1; then lsof -i "tcp:${API_PORT}" >&2 || true; fi
  exit 1
fi

nohup .venv/bin/python -m uvicorn backend.api.main:app \
  --host 127.0.0.1 --port "${API_PORT}" > "$LOG" 2>&1 &
echo $! > "$PIDFILE"

STARTED="$(cat "$PIDFILE")"
for _ in $(seq 1 40); do
  # Whose health is this? If the server we just started is gone, the answer is
  # coming from somebody else and "ready" would be a lie about which code is
  # running. That is the defect this check exists for.
  if ! alive "$STARTED"; then
    echo "the backend this script started (pid $STARTED) exited" >&2
    tail -20 "$LOG" >&2
    exit 1
  fi
  if curl -fsS "http://localhost:${API_PORT}/api/v1/health" > /dev/null 2>&1; then
    echo "backend ready on ${API_PORT} (pid ${STARTED})"
    exit 0
  fi
  sleep 1
done
echo "backend did not answer /api/v1/health" >&2
tail -20 "$LOG" >&2
exit 1
