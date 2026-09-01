#!/usr/bin/env bash
#
# What has to be true before the CreditProbe API serves a request.
#
#   1. PostgreSQL is accepting connections, with these credentials
#   2. The demonstration bootstrap has run and passed its readiness checks
#
# Step 2 used to be three separate things done here, in shell, with the rest
# of the setup living in scripts a presenter was expected to run by hand. A
# fresh Mac ran `docker compose up --build`, got the Saudi portfolio and
# nothing else, and the API came up reporting itself healthy on an empty
# product: no corporate book, no scorecard months, no registered catalogue, no
# Data Builder domains, no workspace, no portfolio review.
#
# So the sequence lives in `backend/bootstrap`, as data, with a probe per step
# and a verification pass at the end — and this file runs it. One command, and
# it is the same command a developer runs locally, so the thing that is tested
# is the thing that ships.
#
# Nothing here destroys anything. Every step asks whether it is needed before
# doing anything, so a restart does the work once and a volume half-built by
# an interrupted start finishes the half that is missing.
set -euo pipefail

say() { echo "[creditprobe] $*"; }

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
print(f"[creditprobe] Could not connect to PostgreSQL after 60 seconds: {last}", file=sys.stderr)
print("[creditprobe] Check it with:  docker compose logs db", file=sys.stderr)
sys.exit(1)
PY
  say "PostgreSQL is ready."
else
  say "No DATABASE_URL set — starting without a database. History and Trace"
  say "versions will not be stored, and the demonstration cannot be seeded."
fi

# --------------------------------------------------- 2. the demonstration

# The first start builds three synthetic universes and runs a portfolio
# review, which takes a few minutes. Every later start finds them and skips.
#
# The exit code is not ignored. A required step that fails stops the
# bootstrap, and the marker file below is what the health check reads — so a
# deployment whose corporate book failed to build reports NOT ready instead of
# reporting healthy with an empty Borrower 360 screen. That silent success is
# the defect this whole arrangement exists to prevent.
# The marker is written BY the bootstrap, to a path, from its structured
# result — not captured off this script's stdout. It used to be captured, and
# the builders' own progress lines ("> Building the corporate universe") went
# into the file ahead of the JSON, so the health check's json.loads failed
# with "Expecting value: line 1 column 1". The API was serving the whole time;
# the container simply never left `health: starting`, the frontend never
# started because it waits on backend health, and localhost:3000 refused the
# connection. Nothing printed anywhere can reach the marker now.
READY_MARKER="${CREDITPROBE_READY_MARKER:-/tmp/creditprobe-bootstrap.json}"
rm -f "${READY_MARKER}" "${READY_MARKER}.failed"

say "Preparing the demonstration (first start builds the data; later starts skip)..."
if python scripts/bootstrap_demo.py --marker "${READY_MARKER}" >&2; then
  say "Demonstration bootstrap complete and verified."
else
  status=$?
  cp "${READY_MARKER}" "${READY_MARKER}.failed" 2>/dev/null || true
  say "DEMONSTRATION BOOTSTRAP DID NOT PASS (exit ${status})."
  say "The API will start so the failure can be inspected, but the container"
  say "will report UNHEALTHY until it passes. What failed:"
  python scripts/bootstrap_demo.py --check 2>/dev/null | sed 's/^/[creditprobe]   /' || true
  say "Re-run one step with:  docker compose exec backend \\"
  say "    python scripts/bootstrap_demo.py --step <name>"
fi

# ------------------------------------------------------------------ 3. serve

say "Starting the CreditProbe API on 0.0.0.0:${API_PORT:-8000}"
exec "$@"
