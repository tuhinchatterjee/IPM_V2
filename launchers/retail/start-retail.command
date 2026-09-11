#!/usr/bin/env bash
#
# Start the CreditProbe Saudi retail demonstration.
#
# Double-click this file. It resolves its own location, so it does not care
# what directory Terminal happens to open in.
#
# It starts the RETAIL installation only:
#   frontend  http://localhost:5328
#   backend   http://localhost:8328
#   data      data/retail/analytics
#   catalogue metadata/retail
#
# It never touches the frozen presentations' ports, and it never stops a process
# it did not start.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"

RETAIL_FRONTEND_PORT=5328
RETAIL_BACKEND_PORT=8328
RUN_DIR="$ROOT/var/retail"
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

say "CreditProbe — Saudi retail demonstration"
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
say "Checking the retail dataset..."
"$PYTHON" "$ROOT/scripts/check_retail_ready.py" --quiet \
  || die "the retail readiness check did not pass. Run it without --quiet to see why."

# ---- 4. ports: only ours, and only if free ---------------------------------
port_owner() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -1
}
for port in "$RETAIL_BACKEND_PORT" "$RETAIL_FRONTEND_PORT"; do
  owner="$(port_owner "$port" || true)"
  if [ -n "$owner" ]; then
    cmd="$(ps -o command= -p "$owner" 2>/dev/null || echo '?')"
    case "$cmd" in
      *retail*|*8328*|*5328*)
        say "  port $port is already served by this retail installation (pid $owner)" ;;
      *)
        die "port $port is in use by pid $owner ($cmd), which is not the retail
installation. Nothing has been stopped. Free the port yourself, or change the
retail port in this launcher." ;;
    esac
  fi
done

# ---- 5. start the retail backend, then the retail frontend -----------------
export DATA_ANALYTICS_DIR="$ROOT/data/retail/analytics"
export DATA_CURATED_DIR="$ROOT/data/retail/curated"
export METADATA_DIR="$ROOT/metadata/retail"
export UPLOAD_DIR="$RUN_DIR/uploads"
export LOG_DIR="$LOG_DIR"
export API_PORT="$RETAIL_BACKEND_PORT"
# The browser calls the backend from the retail frontend's origin. Without
# this the page loads and every API check passes while the screen says the
# backend is offline.
export CORS_ORIGINS="http://localhost:${RETAIL_FRONTEND_PORT},http://127.0.0.1:${RETAIL_FRONTEND_PORT}"
export CREDITPROBE_PRODUCT_PROFILE="retail"

say ""
say "Starting the retail backend on $RETAIL_BACKEND_PORT..."
"$PYTHON" -m uvicorn backend.api.main:app \
  --host 127.0.0.1 --port "$RETAIL_BACKEND_PORT" >>"$BACKEND_LOG" 2>&1 &
echo $! > "$BACKEND_PIDFILE"

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$RETAIL_BACKEND_PORT/api/v1/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl -fsS "http://127.0.0.1:$RETAIL_BACKEND_PORT/api/v1/health" >/dev/null 2>&1 \
  || die "the retail backend did not become healthy on $RETAIL_BACKEND_PORT."

say "Starting the retail frontend on $RETAIL_FRONTEND_PORT..."
(
  cd "$ROOT/frontend"
  # The SAME hostname the browser is opened at, below. The session cookie is
  # host-only and SameSite=Lax, so a page served from localhost calling an API
  # at 127.0.0.1 is a CROSS-SITE request: the browser withholds the cookie and
  # every authenticated call answers 401. The screen then says "You are signed
  # out" while the backend is perfectly healthy, and both chat boxes are dead.
  # Host must match; the port does not matter to a cookie.
  NEXT_PUBLIC_API_URL="http://localhost:$RETAIL_BACKEND_PORT" \
  PORT="$RETAIL_FRONTEND_PORT" \
  npm run dev >>"$FRONTEND_LOG" 2>&1 &
  echo $! > "$FRONTEND_PIDFILE"
)

for _ in $(seq 1 120); do
  if curl -fsS "http://127.0.0.1:$RETAIL_FRONTEND_PORT" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl -fsS "http://127.0.0.1:$RETAIL_FRONTEND_PORT" >/dev/null 2>&1 \
  || die "the retail frontend did not answer on $RETAIL_FRONTEND_PORT."

say ""
say "Retail installation is up."
say "  open   http://localhost:$RETAIL_FRONTEND_PORT"
say "  stop   launchers/retail/stop-retail.command"
say ""
command -v open >/dev/null 2>&1 && open "http://localhost:$RETAIL_FRONTEND_PORT" || true
