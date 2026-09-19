#!/usr/bin/env bash
#
# Stops the candidate, and only the candidate.
#
# Every process is stopped by the pid THIS launcher wrote, after checking the
# pid is still the process it belongs to. There is no pattern matching on
# command lines and no port sweeping: both would find the existing Retail
# Demo, which is the one thing that must survive.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd "$HERE/../.." && pwd -P)"
PID_DIR="$ROOT/var/retail-cockpit-candidate/pids"

stop_one() {
  local name="$1" file="$PID_DIR/$2"
  [ -f "$file" ] || { printf '  %-9s not running\n' "$name"; return; }
  local pid
  pid="$(cat "$file" 2>/dev/null || true)"
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    printf '  %-9s already stopped\n' "$name"
    rm -f "$file"
    return
  fi
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.5
  done
  if kill -0 "$pid" 2>/dev/null; then
    printf '  %-9s did not stop (pid %s) — left alone rather than forced\n' \
      "$name" "$pid"
  else
    printf '  %-9s stopped\n' "$name"
    rm -f "$file"
  fi
}

printf '\nStopping the Retail Demo candidate\n'
stop_one frontend frontend.pid
stop_one engine   engine.pid
stop_one backend  backend.pid
printf '\nThe existing Retail Demo was not touched.\n\n'
