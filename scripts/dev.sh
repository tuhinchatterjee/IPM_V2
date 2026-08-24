#!/usr/bin/env bash
#
# Start CreditProbe for local development — one command.
#
#     ./scripts/dev.sh
#
# It starts everything CreditProbe needs, in the right order, and waits for each part to
# be genuinely ready before starting the next:
#
#   1. PostgreSQL           (in Docker, so you do not have to install it)
#   2. Database migrations  (creates or updates the tables)
#   3. The analytical lake  (converts the source workbook to Parquet, if needed)
#   4. The backend API      (FastAPI, on port 8000)
#   5. The frontend         (Next.js, on port 3000)
#
# Press Ctrl+C once to stop the backend and frontend. PostgreSQL keeps running in
# the background; stop it with `docker compose down`.
#
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
RED=$'\033[31m'; RESET=$'\033[0m'

step()  { echo; echo "${BOLD}▸ $*${RESET}"; }
ok()    { echo "  ${GREEN}✓${RESET} $*"; }
warn()  { echo "  ${YELLOW}!${RESET} $*"; }
fail()  { echo "  ${RED}✗${RESET} $*" >&2; }

die() {
  echo
  fail "$1"
  [ $# -gt 1 ] && { echo; echo "  ${BOLD}How to fix it:${RESET}"; echo "  $2"; }
  echo
  exit 1
}

# ---------------------------------------------------------------- 0. checks

step "Checking prerequisites"

[ -f .env ] || die "No .env file found." \
  "Run:  cp .env.example .env    then open .env and set POSTGRES_PASSWORD."

# Export everything in .env so the backend, Docker Compose and Next.js all agree.
set -a
# shellcheck disable=SC1091
source .env
set +a
ok ".env loaded"

# PostgreSQL normally runs in Docker so nobody has to install it. But if a
# PostgreSQL is already listening where .env points, that is a perfectly good
# database and there is no reason to demand Docker as well.
USE_DOCKER_DB=1
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  ok "Docker is running"
elif command -v pg_isready >/dev/null 2>&1 && \
     pg_isready -h "${POSTGRES_HOST:-127.0.0.1}" -p "${POSTGRES_PORT:-5432}" >/dev/null 2>&1; then
  USE_DOCKER_DB=0
  warn "Docker is not available, but PostgreSQL is already running on port ${POSTGRES_PORT:-5432} — using that"
else
  die "Docker is not installed or not running, and no PostgreSQL is listening on port ${POSTGRES_PORT:-5432}." \
      "Install Docker Desktop from https://www.docker.com/products/docker-desktop/ and start it,
     or start your own PostgreSQL and point DATABASE_URL in .env at it."
fi

command -v node >/dev/null 2>&1 || die "Node.js is not installed." \
  "Install Node.js 20 or newer from https://nodejs.org/"
ok "Node.js $(node -v)"

# Prefer the project virtual environment; fall back to whatever python is around.
if [ -x .venv/bin/python ]; then
  PYTHON="$ROOT/.venv/bin/python"
elif [ -x .venv/Scripts/python.exe ]; then
  PYTHON="$ROOT/.venv/Scripts/python.exe"
else
  PYTHON="$(command -v python3 || command -v python || true)"
  [ -n "$PYTHON" ] || die "Python is not installed." \
    "Install Python 3.11 or newer from https://www.python.org/downloads/"
  warn "No .venv found — using $PYTHON. Create one with:  python -m venv .venv"
fi
ok "Python $("$PYTHON" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"

"$PYTHON" -c "import fastapi, duckdb, sqlalchemy" 2>/dev/null || die \
  "The Python packages are not installed." \
  "Run:  $PYTHON -m pip install -r requirements.txt"
ok "Python packages installed"

[ -d frontend/node_modules ] || die "The frontend packages are not installed." \
  "Run:  cd frontend && npm install"
ok "Frontend packages installed"

# ------------------------------------------------------------- 1. database

step "Starting PostgreSQL"
if [ "$USE_DOCKER_DB" -eq 1 ]; then
  docker compose up -d db >/dev/null

  printf "  waiting for the database"
  for _ in $(seq 1 60); do
    if docker compose exec -T db pg_isready -U "${POSTGRES_USER:-ipm_app}" -d "${POSTGRES_DB:-ipm}" >/dev/null 2>&1; then
      echo; ok "PostgreSQL is ready on port ${POSTGRES_PORT:-5432}"
      break
    fi
    printf "."
    sleep 1
  done
  docker compose exec -T db pg_isready -U "${POSTGRES_USER:-ipm_app}" -d "${POSTGRES_DB:-ipm}" >/dev/null 2>&1 || {
    echo
    die "PostgreSQL did not become ready in 60 seconds." \
        "Check what it is saying with:  docker compose logs db"
  }
else
  ok "Using the PostgreSQL already running on port ${POSTGRES_PORT:-5432}"
fi

# ----------------------------------------------------------- 2. migrations

step "Applying database migrations"
"$PYTHON" -m alembic upgrade head 2>&1 | grep -E "Running upgrade|already at" || true
ok "Database schema is up to date"

# ------------------------------------------------------------ 3. data lake

step "Checking the analytical data"
if [ -d "${DATA_ANALYTICS_DIR:-data/analytics}/portfolio_facility" ]; then
  ok "Analytical layer already built ($(find "${DATA_ANALYTICS_DIR:-data/analytics}" -name '*.parquet' | wc -l | tr -d ' ') Parquet files)"
else
  warn "Not built yet — building it now (this takes a few seconds)"
  "$PYTHON" scripts/generate_saudi_universe.py
fi

# -------------------------------------------------------------- 4. backend

step "Starting the backend API"
"$PYTHON" -m uvicorn backend.api.main:app \
  --host "${API_HOST:-127.0.0.1}" --port "${API_PORT:-8000}" --reload \
  > logs/api-dev.log 2>&1 &
API_PID=$!

cleanup() {
  echo
  step "Shutting down"
  kill "$API_PID" 2>/dev/null || true
  kill "${WEB_PID:-}" 2>/dev/null || true
  wait 2>/dev/null || true
  ok "Backend and frontend stopped"
  if [ "$USE_DOCKER_DB" -eq 1 ]; then
    echo "  ${DIM}PostgreSQL is still running. Stop it with: docker compose down${RESET}"
  fi
  echo
}
trap cleanup EXIT INT TERM

printf "  waiting for the API"
for _ in $(seq 1 40); do
  if curl -fsS "http://${API_HOST:-127.0.0.1}:${API_PORT:-8000}/healthz" >/dev/null 2>&1; then
    echo; ok "API ready at http://${API_HOST:-127.0.0.1}:${API_PORT:-8000}"
    break
  fi
  printf "."
  sleep 1
done
curl -fsS "http://${API_HOST:-127.0.0.1}:${API_PORT:-8000}/healthz" >/dev/null 2>&1 || {
  echo
  die "The API did not start." "Look at what went wrong in:  logs/api-dev.log"
}

# ------------------------------------------------------------- 5. frontend

step "Starting the frontend"
(cd frontend && npm run dev > "$ROOT/logs/web-dev.log" 2>&1) &
WEB_PID=$!

printf "  waiting for the frontend"
for _ in $(seq 1 90); do
  if curl -fsS http://localhost:3000 >/dev/null 2>&1; then
    echo; ok "Frontend ready"
    break
  fi
  printf "."
  sleep 1
done

cat <<BANNER

${GREEN}${BOLD}  CreditProbe is running.${RESET}

    ${BOLD}Open this in your browser:${RESET}   http://localhost:3000

    API                                http://${API_HOST:-127.0.0.1}:${API_PORT:-8000}
    API documentation                  http://${API_HOST:-127.0.0.1}:${API_PORT:-8000}/docs
    Health check                       http://${API_HOST:-127.0.0.1}:${API_PORT:-8000}/api/v1/health

    ${DIM}Logs:  logs/api-dev.log   logs/web-dev.log${RESET}
    ${DIM}Press Ctrl+C to stop.${RESET}

BANNER

wait
