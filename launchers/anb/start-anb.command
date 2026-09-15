#!/usr/bin/env bash
#
# Start the Arab National Bank retail demonstration build.
#
# Double-click this file. It resolves its own location, so it does not care
# what directory Terminal happens to open in.
#
# It starts the ANB build only:
#   frontend  http://localhost:5330
#   backend   http://localhost:8330
#   data      data/retail/analytics
#   catalogue metadata/retail
#   run dir   var/anb
#
# ON THE PORTS
#
# 5330 and 8330, not 5328 and 8328. The accepted retail presentation runs on
# 5328/8328 and is presentation-safe; this build is developed alongside it and
# must never be able to take its ports, its pidfiles or its logs. The numbers
# are two apart rather than one on purpose: a launcher that differs from a
# frozen one by a single digit is a launcher somebody edits by accident on the
# morning of a demonstration.
#
# The two builds share the repository and therefore the dataset directory. They
# are different CHECKOUTS of it — this one belongs in its own worktree — so the
# frozen presentation keeps the book it was accepted with and this one has its
# own. Running both from one working copy would give them one dataset, and the
# first rebuild would change the frozen presentation's numbers underneath it.
#
# It never touches the frozen presentation's ports, and it never stops a
# process it did not start.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"

ANB_FRONTEND_PORT=5330
ANB_BACKEND_PORT=8330
#: The frozen presentation's ports. Never started, never stopped, never bound.
#: Named here so the check below is against a written-down number rather than
#: against whatever the variables above happen to hold after an edit.
FROZEN_FRONTEND_PORT=5328
FROZEN_BACKEND_PORT=8328

if [ "$ANB_FRONTEND_PORT" = "$FROZEN_FRONTEND_PORT" ] \
   || [ "$ANB_BACKEND_PORT" = "$FROZEN_BACKEND_PORT" ]; then
  printf '%s\n' "" \
    "FAILED: this launcher is configured on the frozen presentation's ports" \
    "($FROZEN_FRONTEND_PORT / $FROZEN_BACKEND_PORT). It will not start." \
    "Change ANB_FRONTEND_PORT and ANB_BACKEND_PORT at the top of this file." ""
  exit 1
fi
RUN_DIR="$ROOT/var/anb"
LOG_DIR="$RUN_DIR/logs"
mkdir -p "$LOG_DIR" "$RUN_DIR"

BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
BACKEND_PIDFILE="$RUN_DIR/backend.pid"
FRONTEND_PIDFILE="$RUN_DIR/frontend.pid"

say() { printf '%s\n' "$*"; }
die() {
  say ""
  say "FAILED: $*"
  say ""
  say "  backend log   $BACKEND_LOG"
  say "  frontend log  $FRONTEND_LOG"
  say ""
  exit 1
}

say "CreditProbe — Arab National Bank retail demonstration build"
say "Synthetic Saudi retail demonstration data — not ANB customer data or approved models."
say ""

# ---- 1. build identity -----------------------------------------------------
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
say "  branch        $BRANCH"
say "  commit        $COMMIT"

# ---- 2. environment and isolated data paths --------------------------------
PYTHON="$ROOT/.venv/bin/python"
[ -x "$PYTHON" ] || die "no virtual environment at .venv — run 'uv sync' first."

MANIFEST="$ROOT/metadata/retail/retail_dataset_manifest.json"
[ -f "$MANIFEST" ] || die "the retail dataset has not been built. Run:
    .venv/bin/python scripts/build_retail_demo.py"

# ---- 3. readiness: 25 months, pinned version, reconciled totals ------------
say ""
say "Checking the demonstration dataset..."
"$PYTHON" "$ROOT/scripts/check_retail_ready.py" --quiet \
  || die "the retail readiness check did not pass. Run it without --quiet to see why."

# ---- 4. ports: only ours, and only if free ---------------------------------
port_owner() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -1
}

# Whether a pid is this build's: recorded in var/anb, or descended from
# something that is. Asked rather than guessed from a command line, because
# the process actually holding the frontend port is three forks below the one
# this launcher was able to record.
own_pid() {
  local target="$1" recorded kid
  for pidfile in "$BACKEND_PIDFILE" "$FRONTEND_PIDFILE"; do
    [ -f "$pidfile" ] || continue
    while IFS= read -r recorded; do
      case "$recorded" in ""|*[!0-9]*) continue ;; esac
      [ "$recorded" = "$target" ] && return 0
      for kid in $(descendants_of "$recorded"); do
        [ "$kid" = "$target" ] && return 0
      done
    done < "$pidfile"
  done
  return 1
}

descendants_of() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    descendants_of "$child"
    printf '%s\n' "$child"
  done
}
for port in "$ANB_BACKEND_PORT" "$ANB_FRONTEND_PORT"; do
  owner="$(port_owner "$port" || true)"
  if [ -n "$owner" ]; then
    cmd="$(ps -o command= -p "$owner" 2>/dev/null || echo '?')"
    case "$cmd" in
      *8330*|*5330*)
        say "  port $port is already served by this ANB build (pid $owner)" ;;
      *)
        # It may still be ours. The frontend's port is held by next-server,
        # three forks below the npm we recorded, and its command line carries
        # no port at all — so the pattern above cannot recognise it and this
        # branch used to tell the presenter their own leftover frontend was
        # somebody else's process. The pidfiles say whose it is: if the holder
        # is one of them, or a descendant of one, it is this build's.
        if own_pid "$owner"; then
          say "  port $port is already served by this ANB build (pid $owner)"
        else
          die "port $port is in use by pid $owner ($cmd), which is not the ANB
build. Nothing has been stopped — in particular, if that is the frozen 5328/8328
presentation, it is still running. Free the port yourself, or change the ANB
port in this launcher."
        fi ;;
    esac
  fi
done

# ---- 5. start the retail backend, then the retail frontend -----------------
export DATA_ANALYTICS_DIR="$ROOT/data/retail/analytics"
export DATA_CURATED_DIR="$ROOT/data/retail/curated"
export METADATA_DIR="$ROOT/metadata/retail"
export UPLOAD_DIR="$RUN_DIR/uploads"
export LOG_DIR="$LOG_DIR"
export API_PORT="$ANB_BACKEND_PORT"
# The browser calls the backend from the retail frontend's origin. Without
# this the page loads and every API check passes while the screen says the
# backend is offline.
export CORS_ORIGINS="http://localhost:${ANB_FRONTEND_PORT},http://127.0.0.1:${ANB_FRONTEND_PORT}"
export CREDITPROBE_PRODUCT_PROFILE="retail"

say ""
say "Starting the ANB backend on $ANB_BACKEND_PORT..."
"$PYTHON" -m uvicorn backend.api.main:app \
  --host 127.0.0.1 --port "$ANB_BACKEND_PORT" >>"$BACKEND_LOG" 2>&1 &
echo $! > "$BACKEND_PIDFILE"

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$ANB_BACKEND_PORT/api/v1/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl -fsS "http://127.0.0.1:$ANB_BACKEND_PORT/api/v1/health" >/dev/null 2>&1 \
  || die "the ANB backend did not become healthy on $ANB_BACKEND_PORT."

say "Starting the ANB frontend on $ANB_FRONTEND_PORT..."
(
  cd "$ROOT/frontend"
  # The SAME hostname the browser is opened at, below. The session cookie is
  # host-only and SameSite=Lax, so a page served from localhost calling an API
  # at 127.0.0.1 is a CROSS-SITE request: the browser withholds the cookie and
  # every authenticated call answers 401. The screen then says "You are signed
  # out" while the backend is perfectly healthy, and both chat boxes are dead.
  # Host must match; the port does not matter to a cookie.
  NEXT_PUBLIC_API_URL="http://localhost:$ANB_BACKEND_PORT" \
  NEXT_PUBLIC_PRODUCT_PROFILE="retail" \
  PORT="$ANB_FRONTEND_PORT" \
  npm run dev >>"$FRONTEND_LOG" 2>&1 &
  echo $! > "$FRONTEND_PIDFILE"
)

for _ in $(seq 1 120); do
  if curl -fsS "http://127.0.0.1:$ANB_FRONTEND_PORT" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl -fsS "http://127.0.0.1:$ANB_FRONTEND_PORT" >/dev/null 2>&1 \
  || die "the ANB frontend did not answer on $ANB_FRONTEND_PORT."

say ""
say "ANB demonstration build is up."
say "  open   http://localhost:$ANB_FRONTEND_PORT"
say "  stop   launchers/anb/stop-anb.command"
say ""
command -v open >/dev/null 2>&1 && open "http://localhost:$ANB_FRONTEND_PORT" || true
