#!/usr/bin/env bash
#
# What has to be true before the CreditProbe API can serve a request, in order.
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

# The demonstration book is SIMULATED rather than read from a file: it is a
# Saudi corporate portfolio of ~16,000 facilities across 15 quarters, with the
# IFRS 9 staging, rating history and macroeconomic series that go with it. One
# fixed seed, so every machine gets the identical universe.
#
# The raw workbook under data/raw is left alone. `scripts/build_data_lake.py`
# still turns it into the same governed shape, which is how a client dataset is
# onboarded — the generated universe is only what is there before one is.
ANALYTICS_DIR="${DATA_ANALYTICS_DIR:-data/analytics}"

# Every dataset the generator produces. Checking the whole list rather than one
# of them matters on an UPGRADE: a volume built by an earlier version has
# portfolio_facility and would pass a single-directory check, while the datasets
# added since would silently not exist — and the analyses that read them would
# report no data rather than an error.
EXPECTED_DATASETS="portfolio_facility ifrs9_staging customer_ratings macro_saudi \
borrower_financials facility_delinquency credit_memo_signals collateral_register \
covenant_tests facility_limits watchlist_register recoveries payment_history \
group_structure rating_transitions risk_appetite_limits pd_model_performance \
scenario_definitions facility_profitability climate_risk"

missing=""
for dataset in ${EXPECTED_DATASETS}; do
  if [ ! -d "${ANALYTICS_DIR}/${dataset}" ]; then
    missing="${missing} ${dataset}"
  fi
done

if [ -z "${missing}" ]; then
  say "Analytical layer already built."
else
  say "Building the demonstration universe (~20 seconds). Missing:${missing}"
  python scripts/generate_saudi_universe.py
  say "Analytical layer built."
fi

# --------------------------------------------------- 3b. the demo accounts

# Idempotent, and it NEVER changes a password that already exists — so a
# restart cannot undo a password somebody set, and this can run on every boot.
if [ -n "${DATABASE_URL:-}" ]; then
  python scripts/seed_demo_users.py || say "Could not seed the demonstration users."
fi

# ------------------------------------------------------------------ 4. serve

say "Starting the CreditProbe API on 0.0.0.0:${API_PORT:-8000}"
exec "$@"
