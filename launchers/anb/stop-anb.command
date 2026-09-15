#!/usr/bin/env bash
#
# Stop the Arab National Bank demonstration build — and nothing else.
#
# Every process this stops was started by start-anb.command and recorded its
# own pid in var/anb. There is no kill-by-name and no kill-by-port here: a
# broad process-name kill would take the frozen 5328/8328 presentation down
# with it, which is the one outcome this file exists to make impossible.
#
# WHY IT WALKS THE TREE
#
# The first version stopped the recorded pid, having checked that pid's own
# command line for one of our ports. That works for the backend, whose
# recorded pid IS uvicorn with `--port 8330` on its command line. It does not
# work for the frontend at all: `npm run dev` forks `next dev`, which forks
# `next-server`, and it is the grandchild three levels down that holds port
# 5330. The recorded pid is npm's, npm's command line carries no port, so the
# check refused to touch it — and the script printed "Done" while the frontend
# went on serving. The next start then died on a port it could not have, and
# told the presenter it was held by something that was not the ANB build.
#
# So a recorded pid is now stopped along with its descendants. That is still
# narrower than killing by name: the frozen presentation is not a descendant
# of anything recorded in var/anb, and it cannot become one.
#
# The command-line check is kept, and it is now doing the job it was really
# needed for rather than the job it was written for. A pidfile can outlive the
# process it names and the number in it can be handed to something else
# entirely, so a recorded pid is stopped only if it still looks like a thing
# this launcher starts.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
RUN_DIR="$ROOT/var/anb"

# Children first. Stopping a parent reparents its children to init, and a
# reparented next-server holds the port with nothing left pointing at it.
descendants() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    descendants "$child"
    printf '%s\n' "$child"
  done
}

# A pid this launcher plausibly started. Not the authority — the pidfile is —
# just a guard against a recycled pid belonging to something else by now.
ours() {
  case "$1" in
    *8330*|*5330*|*uvicorn*|*"npm run dev"*|*"next dev"*|*next-server*|*node*)
      return 0 ;;
    *) return 1 ;;
  esac
}

end_pid() {
  local pid="$1" what="$2" waited=0
  kill -0 "$pid" 2>/dev/null || return 0
  kill "$pid" 2>/dev/null && printf '  %s: stopping pid %s\n' "$what" "$pid"
  while kill -0 "$pid" 2>/dev/null && [ "$waited" -lt 20 ]; do
    sleep 1; waited=$((waited + 1))
  done
  if kill -0 "$pid" 2>/dev/null; then
    printf '  %s: pid %s did not stop in %ss; ending it\n' "$what" "$pid" "$waited"
    kill -9 "$pid" 2>/dev/null || true
    sleep 1
  fi
  if kill -0 "$pid" 2>/dev/null; then
    printf '  %s: pid %s is STILL running. Stop it by hand before starting again.\n' \
      "$what" "$pid"
  else
    printf '  %s: stopped pid %s\n' "$what" "$pid"
  fi
}

stop_one() {
  local pidfile="$1" what="$2"
  [ -f "$pidfile" ] || { printf '  %s: no pid file, nothing to stop\n' "$what"; return 0; }

  local stopped=0 pid cmd kid
  while IFS= read -r pid; do
    [ -n "$pid" ] || continue
    case "$pid" in (*[!0-9]*)
      printf '  %s: %s is not a pid, skipping\n' "$what" "$pid"; continue ;;
    esac
    if ! kill -0 "$pid" 2>/dev/null; then
      printf '  %s: pid %s is not running\n' "$what" "$pid"
      continue
    fi
    cmd="$(ps -o command= -p "$pid" 2>/dev/null || true)"
    if ! ours "$cmd"; then
      printf '  %s: pid %s is %s — NOT an ANB process, leaving it alone\n' \
        "$what" "$pid" "${cmd:-unknown}"
      continue
    fi
    for kid in $(descendants "$pid"); do
      end_pid "$kid" "$what (child)"
    done
    end_pid "$pid" "$what"
    stopped=$((stopped + 1))
  done < "$pidfile"

  [ "$stopped" -gt 0 ] && rm -f "$pidfile"
  return 0
}

printf 'Stopping the ANB demonstration build\n'
stop_one "$RUN_DIR/frontend.pid" "frontend"
stop_one "$RUN_DIR/backend.pid" "backend"

# Said out loud rather than assumed. "Done" printed over a port that is still
# held is the message that sends a presenter into the next start with no idea
# why it refuses.
still_held=0
for port in 5330 8330; do
  holder="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1 || true)"
  if [ -n "$holder" ]; then
    still_held=1
    printf '  WARNING: port %s is still held by pid %s (%s)\n' \
      "$port" "$holder" "$(ps -o command= -p "$holder" 2>/dev/null || echo unknown)"
  fi
done
if [ "$still_held" -eq 0 ]; then
  printf 'Done. Both ports are free, and the frozen 5328/8328 presentation was not touched.\n'
else
  printf 'Stopped what it could. The frozen 5328/8328 presentation was not touched.\n'
fi
