#!/usr/bin/env bash
#
# What has to be true before the IPM API can serve a request, in order.
#
#   1. PostgreSQL is accepting connections, with these credentials
#   2. The database schema is up to date
#   3. The analytical Parquet layer exists
#
# Compose already waits for the database's own health check, so step 1 is a
# short belt-and-braces retry rather than the primary mechanism. It connects
# with the application's real DATABASE_URL rather than only probing the port,
# so a wrong password fails here with a clear message instead of surfacing as a
# mysterious 500 on the first request.
#
# Nothing here destroys anything. `alembic upgrade head` only applies migrations
# that have not run yet, and the data lake is built only when it is missing.
set -euo pipefail

say() { echo "[ipm] $*"; }

# ------------------------------------------------------------ 1. the database

if [ -n "${DATABASE_URL:-}" ]; then
  say "Waiting for PostgreSQL..."
  python - <<'PY'
import os, sys, time

import psycopg

url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
last = ""
for _ in range(60):
    try:
        psycopg.connect(url, connect_timeout=3).close()
        sys.exit(0)
    except Exception as e:  # not ready yet, or wrong credentials
        last = str(e).strip().splitlines()[0] if str(e).strip() else repr(e)
        time.sleep(1)
print(f"[ipm] Could not connect to PostgreSQL after 60 seconds: {last}", file=sys.stderr)
print("[ipm] Check it with:  docker compose logs db", file=sys.stderr)
sys.exit(1)
PY
  say "PostgreSQL is ready."

  # ---------------------------------------------------------- 2. the schema
  say "Applying database migrations..."
  python -m alembic upgrade head
  say "Database schema is up to date."
else
  say "No DATABASE_URL set — starting without a database. History and Trace"
  say "versions will not be stored."
fi

# ------------------------------------------------------- 3. the analytics layer

ANALYTICS_DIR="${DATA_ANALYTICS_DIR:-data/analytics}"
if [ -d "${ANALYTICS_DIR}/portfolio_facility" ]; then
  say "Analytical layer already built."
else
  say "Building the analytical layer from data/raw (first run only, ~20 seconds)..."
  python scripts/build_data_lake.py
  say "Analytical layer built."
fi

# ------------------------------------------------------------------ 4. serve

say "Starting the IPM API on 0.0.0.0:${API_PORT:-8000}"
exec "$@"
