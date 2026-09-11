#!/usr/bin/env bash
#
# Stop the CreditProbe Saudi retail demonstration — and nothing else.
#
# Every process this stops was started by start-retail.command and recorded its
# own pid. There is no kill-by-name and no kill-by-port here: a broad
# process-name kill would take the frozen presentations down with it.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
RUN_DIR="$ROOT/var/retail"

stop_one() {
  local pidfile="$1" what="$2"
  [ -f "$pidfile" ] || { printf '  %s: no pid file, nothing to stop\n' "$what"; return 0; }

  # One pid per line, handled one at a time. A newline-joined string passed as
  # a single argument is not a pid, and kill would reject the lot.
  local stopped=0
  while IFS= read -r pid; do
    [ -n "$pid" ] || continue
    case "$pid" in (*[!0-9]*) printf '  %s: %s is not a pid, skipping\n' "$what" "$pid"; continue ;; esac
    if ! kill -0 "$pid" 2>/dev/null; then
      printf '  %s: pid %s is not running\n' "$what" "$pid"
      continue
    fi
    local cmd; cmd="$(ps -o command= -p "$pid" 2>/dev/null || true)"
    case "$cmd" in
      *8328*|*5328*|*retail*)
        # Asked politely, then confirmed. SIGTERM alone was sent and the
        # script returned at once, so "Done" was printed over a process that
        # had not stopped: uvicorn can sit in "Waiting for background tasks to
        # complete" indefinitely, and the next start then finds its port
        # taken. Twenty seconds is longer than any request this product makes.
        kill "$pid" 2>/dev/null && printf '  %s: stopping pid %s\n' "$what" "$pid"
        waited=0
        while kill -0 "$pid" 2>/dev/null && [ "$waited" -lt 20 ]; do
          sleep 1; waited=$((waited+1))
        done
        if kill -0 "$pid" 2>/dev/null; then
          printf '  %s: pid %s did not stop in %ss; ending it\n' \
            "$what" "$pid" "$waited"
          kill -9 "$pid" 2>/dev/null || true
          sleep 1
        fi
        if kill -0 "$pid" 2>/dev/null; then
          printf '  %s: pid %s is STILL running. Stop it by hand before starting again.\n' \
            "$what" "$pid"
        else
          printf '  %s: stopped pid %s\n' "$what" "$pid"
        fi
        stopped=$((stopped+1)) ;;
      *)
        printf '  %s: pid %s is %s — NOT the retail process, leaving it alone\n' \
          "$what" "$pid" "${cmd:-unknown}" ;;
    esac
  done < "$pidfile"

  [ "$stopped" -gt 0 ] && rm -f "$pidfile"
  return 0
}

printf 'Stopping the retail installation\n'
stop_one "$RUN_DIR/frontend.pid" "frontend"
stop_one "$RUN_DIR/backend.pid" "backend"
printf 'Done. The frozen presentations were not touched.\n'
