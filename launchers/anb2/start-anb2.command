#!/usr/bin/env bash
#
# Start the CreditProbe ten-journeys retail build (CP-RA-V2).
#
# Double-click this file. It resolves its own location, so it does not care
# what directory Terminal happens to open in.
#
# It starts THIS build only:
#   frontend  http://localhost:5334
#   backend   http://localhost:8334
#   database  creditprobe_anb_v2   (its own, loaded from .env.anb2)
#   data      data/retail/analytics
#   catalogue metadata/retail
#   run dir   var/anb2
#
# ON THE PORTS, AND ON EVERYTHING IT REFUSES TO TOUCH
#
# Four builds now exist side by side, and three of them are somebody's
# presentation:
#
#   5328 / 8328   the frozen retail presentation
#   5330 / 8330   the accepted ANB Requires Attention demonstration
#   5332 / 8332   the Agentic Project Planner UAT
#   5334 / 8334   THIS build
#
# This launcher binds the fourth pair and refuses to start if any of the other
# three is configured here, checked against written-down numbers rather than
# against whatever the variables happen to hold after an edit. It never stops a
# process it did not start, and it never stops one at all: a port held by
# somebody else is a refusal with the holder named, not a kill.
#
# The database is this build's own. It is read from .env.anb2 rather than
# written here, so the file that holds a connection string is one file and is
# not in the repository.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"

ANB_FRONTEND_PORT=5334
ANB_BACKEND_PORT=8334
#: Every port that belongs to somebody else's build. Written down rather than
#: derived, so an edit to the two above cannot quietly make this check pass.
PROTECTED_PORTS="5328 8328 5330 8330 5332 8332"
for protected in $PROTECTED_PORTS; do
  if [ "$ANB_FRONTEND_PORT" = "$protected" ] \
     || [ "$ANB_BACKEND_PORT" = "$protected" ]; then
    printf '%s\n' "" \
      "FAILED: this launcher is configured on port $protected, which belongs" \
      "to another build (5328/8328 frozen, 5330/8330 accepted ANB demo," \
      "5332/8332 Planner UAT). It will not start." \
      "Change ANB_FRONTEND_PORT and ANB_BACKEND_PORT at the top of this file." ""
    exit 1
  fi
done
RUN_DIR="$ROOT/var/anb2"
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

say "CreditProbe — ten Saudi retail investigation journeys (CP-RA-V2)"
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

# Whether a pid is this build's: recorded in var/anb2, or descended from
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
      *8334*|*5334*)
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
          die "port $port is in use by pid $owner ($cmd), which is not this
build. NOTHING HAS BEEN STOPPED. If that is the frozen 5328/8328 presentation,
the accepted 5330/8330 ANB demonstration or the 5332/8332 Planner UAT, it is
still running and this launcher will not interfere with it. Free the port
yourself, or change the port at the top of this launcher."
        fi ;;
    esac
  fi
done

# ---- 5. this build's own environment, database and migrations -------------
#
# Loaded from .env.anb2 rather than written here. A connection string in a
# launcher is a connection string in the repository, and the specification is
# explicit that local settings are used without being printed.
ENV_FILE="$ROOT/.env.anb2"
[ -f "$ENV_FILE" ] || die "there is no .env.anb2. Copy .env.anb2.example to
.env.anb2 and set DATABASE_URL to this build's OWN database — not the accepted
demonstration's. The example file explains each setting."
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

case "${DATABASE_URL:-}" in
  *creditprobe_retail*|*creditprobe_anb\?*|*creditprobe_anb)
    die "DATABASE_URL in .env.anb2 points at the accepted demonstration's
database. This build keeps its own so that rebuilding it cannot disturb a demo
somebody is about to give. Point it at creditprobe_anb_v2 (or another database
of your own) and run the migrations." ;;
esac

say ""
say "Checking this build's own database..."
"$PYTHON" -m alembic upgrade head >>"$BACKEND_LOG" 2>&1 \
  || die "the database migrations did not apply. See $BACKEND_LOG.
If the database does not exist yet, create it first:  createdb creditprobe_anb_v2"

say "Checking the published bundle..."
"$PYTHON" - <<'CHECK' || die "no complete bundle is published. Run:
    .venv/bin/python scripts/publish_retail_bundle.py"
import sys
from backend.retail import bundle as bnd
found = bnd.read("metadata/retail")
if found is None or not found.complete:
    sys.exit(1)
print(f"  bundle        {found.bundle_id}  as of {found.as_of}")
CHECK

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
say "  stop   launchers/anb2/stop-anb2.command"
say ""
command -v open >/dev/null 2>&1 && open "http://localhost:$ANB_FRONTEND_PORT" || true
