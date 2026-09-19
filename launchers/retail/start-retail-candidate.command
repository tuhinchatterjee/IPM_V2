#!/usr/bin/env bash
#
# The Retail Demo with the AdvancedCockpit, as a CANDIDATE.
#
# Beside the existing demo, never instead of it: different ports, different
# state, different logs, different pids, its own Cockpit runtime directory.
# `START_CREDITPROBE_RETAIL_DEMO.command` is not touched and the processes it
# started are not touched -- this refuses to start rather than reuse or stop
# anything it did not launch itself.
#
# Three processes, in this order, because each one needs the last:
#   1. the retail API, which is also the authenticated door onto the Cockpit;
#   2. the Cockpit engine, which materialises the book before it can answer;
#   3. the frontend.
#
# READY is printed only when the whole Cockpit path answers -- the engine's
# own capability flags AND a real request through the proxy. A launcher that
# prints READY when a port opens is a launcher that hands over a Cockpit that
# cannot answer anything.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd "$HERE/../.." && pwd -P)"
cd "$ROOT"

# Ports of its own. The demo's 5328/8328 are left alone.
FRONTEND_PORT="${CANDIDATE_FRONTEND_PORT:-5329}"
BACKEND_PORT="${CANDIDATE_BACKEND_PORT:-8329}"
ENGINE_PORT="${CANDIDATE_ENGINE_PORT:-8415}"

RUN_DIR="$ROOT/var/retail-cockpit-candidate"
LOG_DIR="$RUN_DIR/logs"
PID_DIR="$RUN_DIR/pids"
mkdir -p "$LOG_DIR" "$PID_DIR"

BACKEND_LOG="$LOG_DIR/backend.log"
ENGINE_LOG="$LOG_DIR/engine.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"

say() { printf '%s\n' "$*"; }
die() { printf '\n  %s\n\n' "$*" >&2; exit 1; }

say ""
say "CreditProbe Retail Demo — AdvancedCockpit CANDIDATE"
say "  branch $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
say "  commit $(git rev-parse --short HEAD 2>/dev/null || echo '?')"

# ---- 1. what this needs before it starts anything --------------------------
PYTHON="$ROOT/.venv/bin/python"
[ -x "$PYTHON" ] || die "no virtual environment at .venv — run 'uv sync' first."
[ -d "$ROOT/frontend/node_modules" ] || die \
  "frontend/node_modules is missing — run 'npm ci' in frontend/ first. This
  launcher will not symlink or copy one from anywhere else."

ENV_FILE="$ROOT/.env.retail-candidate"
[ -f "$ENV_FILE" ] || die \
  "no $ENV_FILE — copy .env.retail-candidate.example and fill it in."
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

RELEASE="${COCKPIT_V4_RETAIL_RELEASE_ID:-}"
[ -n "$RELEASE" ] || die "COCKPIT_V4_RETAIL_RELEASE_ID is not set in $ENV_FILE."

# The boundary secret, per launch. Never committed, never reused across runs,
# and the same value handed to both processes.
RETAIL_COCKPIT_HOST_SECRET="$("$PYTHON" -c 'import secrets;print(secrets.token_urlsafe(32))')"
export RETAIL_COCKPIT_HOST_SECRET
export RETAIL_COCKPIT_ENGINE_URL="http://127.0.0.1:$ENGINE_PORT"

# ---- 2. ports: refuse, never reclaim ---------------------------------------
port_owner() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -1; }
for port in "$BACKEND_PORT" "$FRONTEND_PORT" "$ENGINE_PORT"; do
  owner="$(port_owner "$port" || true)"
  if [ -n "$owner" ]; then
    die "port $port is already in use by pid $owner. This launcher does not
  stop processes it did not start. Stop it yourself, or set
  CANDIDATE_FRONTEND_PORT / CANDIDATE_BACKEND_PORT / CANDIDATE_ENGINE_PORT."
  fi
done

# ---- 3. the book the Cockpit will read -------------------------------------
"$PYTHON" - <<PY || die "the Cockpit release is not published — run
  scripts/retail_cockpit/publish_release.py"
import sys
sys.path.insert(0, "$ROOT")
from backend.cockpit_v4 import lake
sys.exit(0 if lake.exists("$RELEASE") else 1)
PY
say "  book   $RELEASE"

# ---- 4. the retail API ------------------------------------------------------
export API_PORT="$BACKEND_PORT"
export CORS_ORIGINS="http://localhost:${FRONTEND_PORT},http://127.0.0.1:${FRONTEND_PORT}"
export UPLOAD_DIR="$RUN_DIR/uploads"
export LOG_DIR

say ""
say "Starting the retail API on $BACKEND_PORT..."
"$PYTHON" -m uvicorn backend.api.main:app \
  --host 127.0.0.1 --port "$BACKEND_PORT" >>"$BACKEND_LOG" 2>&1 &
echo $! > "$PID_DIR/backend.pid"

for _ in $(seq 1 60); do
  curl -fsS "http://127.0.0.1:$BACKEND_PORT/api/v1/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://127.0.0.1:$BACKEND_PORT/api/v1/health" >/dev/null 2>&1 \
  || die "the retail API did not become healthy on $BACKEND_PORT."

# ---- 5. the Cockpit engine --------------------------------------------------
#
# This is the slow one, and deliberately so: the book is materialised at
# startup, so the cold open is paid here, by the launcher, instead of by
# whoever asks the first question.
# RETAIL_COCKPIT_OFFLINE is a TESTING mode and says so on the way past. It
# starts the engine with a provider that cannot reach the network, so the
# whole path can be exercised on a machine with no credential: a run is
# accepted, driven by the real worker and settled as a real failure at the
# model call. READY then means the plumbing works. It does NOT mean the
# Cockpit can answer anything, and the banner at the end says so.
ENGINE_ARGS=(--port "$ENGINE_PORT")
if [ -n "${RETAIL_COCKPIT_OFFLINE:-}" ]; then
  ENGINE_ARGS+=(--offline)
  say ""
  say "  !! RETAIL_COCKPIT_OFFLINE is set. No provider will be called and no"
  say "  !! question can be answered. This is for testing the path only."
fi

say "Starting the Cockpit engine on $ENGINE_PORT (materialising the book)..."
"$PYTHON" scripts/retail_cockpit/run_engine.py "${ENGINE_ARGS[@]}" \
  >>"$ENGINE_LOG" 2>&1 &
echo $! > "$PID_DIR/engine.pid"

for _ in $(seq 1 300); do
  curl -fsS "http://127.0.0.1:$ENGINE_PORT/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://127.0.0.1:$ENGINE_PORT/health" >/dev/null 2>&1 \
  || die "the Cockpit engine did not answer on $ENGINE_PORT. See $ENGINE_LOG."

# ---- 6. the frontend --------------------------------------------------------
say "Starting the frontend on $FRONTEND_PORT..."
(
  cd "$ROOT/frontend"
  # `localhost`, matching the browser below: the session cookie is host-only
  # and SameSite=Lax, so a page served from localhost calling 127.0.0.1 is a
  # cross-site request and the cookie is withheld.
  #
  # `same-origin` is what puts the Cockpit behind the retail API rather than
  # on the engine's own port: the client turns every call into a relative
  # /api/v1/cockpit-v4/... against this origin.
  # `same-origin` makes the Cockpit client call THIS origin, which is the
  # Next server -- so Next's own /api/* rewrite has to reach the retail API.
  # It defaults to port 8000 and nothing listens there, which shows up as a
  # 500 on every Cockpit call while the API itself is perfectly healthy.
  BACKEND_INTERNAL_URL="http://127.0.0.1:$BACKEND_PORT" \
  NEXT_PUBLIC_API_URL="http://localhost:$BACKEND_PORT" \
  NEXT_PUBLIC_COCKPIT_V4_API="same-origin" \
  NEXT_PUBLIC_PRODUCT_PROFILE="retail" \
  PORT="$FRONTEND_PORT" \
  npm run dev >>"$FRONTEND_LOG" 2>&1 &
  echo $! > "$PID_DIR/frontend.pid"
)

for _ in $(seq 1 180); do
  curl -fsS "http://127.0.0.1:$FRONTEND_PORT" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://127.0.0.1:$FRONTEND_PORT" >/dev/null 2>&1 \
  || die "the frontend did not answer on $FRONTEND_PORT."

# ---- 7. READY, and only if the Cockpit path actually answers ----------------
say ""
say "Checking the Cockpit path end to end..."
"$PYTHON" scripts/retail_cockpit/check_ready.py \
  --api "http://127.0.0.1:$BACKEND_PORT" \
  --engine "http://127.0.0.1:$ENGINE_PORT" \
  || die "the Cockpit did not come up ready. Nothing was substituted for it.
  The stack is still running; see $ENGINE_LOG and $BACKEND_LOG."

say ""
if [ -n "${RETAIL_COCKPIT_OFFLINE:-}" ]; then
  say "READY (OFFLINE) — the path works end to end; no question can be"
  say "answered, because no provider is configured."
else
  say "READY — Retail Demo (AdvancedCockpit candidate)"
fi
say "  open   http://localhost:$FRONTEND_PORT"
say "  stop   launchers/retail/stop-retail-candidate.command"
say "  logs   $LOG_DIR"
say ""
command -v open >/dev/null 2>&1 && open "http://localhost:$FRONTEND_PORT" || true
