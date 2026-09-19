# Running the candidate

Everything here is read-only against the retail installation's own data and
writes only under `var/retail-cockpit-candidate/`. The existing demo and its
launcher are never touched.

## Once

    uv sync
    npm --prefix frontend ci
    cp .env.retail-candidate.example .env.retail-candidate   # then edit it

`.env.retail-candidate` is gitignored. It needs a `DATABASE_URL`, a
`SECRET_KEY`, and — before any paid run — `COCKPIT_ANTHROPIC_API_KEY` and a
real `COCKPIT_V4_PRICE_CARD`. Names only; nothing here ever prints a value.

## Publish the book the Cockpit reads

    .venv/bin/python scripts/retail_cockpit/publish_release.py --revision 7

Reads `data/retail/analytics` and `metadata/retail` read-only and writes one
immutable release into the Cockpit's own lake. It refuses to overwrite a
release that already exists, and it refuses to publish at all if the
projection fails its gates — which now include the denomination pair, the
source-total reconciliation and the score-migration contract.

Verify what it wrote:

    .venv/bin/python scripts/retail_cockpit/publish_release.py --revision 7 --verify

## Check the numbers

    .venv/bin/python scripts/retail_cockpit/check_oracles.py \
        --release cockpitdata-r1.2.0-c1.0.0-s20260910-p7

Twenty-eight cases, each computed with pandas from the source book by a
different implementation and compared against the engine's own session.

## Start it

    launchers/retail/start-retail-candidate.command

Ports 5329 / 8329 / 8415. It refuses a port in use rather than reclaiming
one, refuses to start without `node_modules` rather than improvising one,
generates the boundary secret per launch, waits for the book to materialise,
and prints READY only after the whole Cockpit path answers.

    launchers/retail/stop-retail-candidate.command

stops only the pids the launcher wrote.

On a machine with no provider credential, `RETAIL_COCKPIT_OFFLINE=1` starts
the engine with a provider that cannot reach the network. The path can then
be exercised end to end, and the banner says READY (OFFLINE) so nobody reads
it as "the Cockpit can answer".

## The gates

| | |
|---|---|
| Integration suite | `.venv/bin/python -m pytest tests/retail_cockpit -q` |
| The ported engine suite, on this book | `COCKPIT_V4_TEST_RELEASE=cockpitdata-r1.2.0-c1.0.0-s20260910-p7 .venv/bin/python -m pytest tests/cockpit_v4 -q` |
| Retail regression | `.venv/bin/python -m pytest tests/retail -q` |
| Everything `check.sh` runs | `bash scripts/check.sh` |
| The port is still the port | `.venv/bin/python scripts/retail_cockpit/verify_port.py` |
| The Cockpit path answers | `.venv/bin/python scripts/retail_cockpit/check_ready.py --api http://127.0.0.1:8329 --engine http://127.0.0.1:8415` |
| The event stream survives the proxy | `.venv/bin/python scripts/retail_cockpit/check_transport.py --proxy http://127.0.0.1:8329/api/v1/cockpit-v4` (against an engine started `--offline --think 8`) |
| Browser | `CANDIDATE_UI_URL=http://localhost:5329 CANDIDATE_API_URL=http://127.0.0.1:8329 CANDIDATE_ENGINE_URL=http://127.0.0.1:8415 node tests/retail_cockpit/browser/candidate.browser.mjs` |
| Memory | `.venv/bin/python scripts/retail_cockpit/benchmark_session.py --limits 1536MB,2048MB --repeat 3` |

## Two things that will bite

**`BACKEND_INTERNAL_URL`.** `NEXT_PUBLIC_COCKPIT_V4_API=same-origin` makes
the Cockpit client call the Next server, so Next's own `/api/*` rewrite has
to reach the retail API. It defaults to port 8000. Unset, every Cockpit call
answers 500 while the API is perfectly healthy. The launcher sets it.

**One engine per runtime directory.** DuckDB names an in-memory database's
spill files after the database, not the process, so two engines sharing
`COCKPIT_V4_RUNTIME_DIR` overwrite each other's temp storage and every query
that touched a spilled table fails with an IO Error naming a temp file. The
candidate entrypoint gives each engine its own spill directory, named for its
port; a stale engine on another port is therefore harmless, but two engines
on the same port are not possible anyway.
