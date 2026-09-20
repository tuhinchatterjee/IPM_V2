# Running the candidate

Everything here is read-only against the retail installation's own data and
writes only under `var/retail-cockpit-candidate/`. The existing demo and its
launcher are never touched.

## Once

    uv sync
    npm --prefix frontend ci
    cp .env.retail-candidate.example .env.retail-candidate   # then edit it

`.env.retail-candidate` is gitignored. It needs a `DATABASE_URL` and a
`SECRET_KEY`; everything else in the template is already right. The model and
the price card are set for live mode, and the credential is **not** in the
file — export it in your shell instead (see **Going live**). Names only;
nothing here ever prints a value.

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

An offline run needs **no model id and no price card**: because the provider
cannot reach a paid API, the runtime is built from an offline capability that
names no model and declares no price
(`backend/retail_cockpit_host/offline.py`). Live mode is unaffected — it
still goes through the engine's own `load_capability`, and the shipped
placeholder card still refuses every real model until you replace it with a
verified schedule.

## Going live

Offline proves the plumbing. Live costs money, so it is deliberate:

    # 1. What a live start would do, and what it would cost. No call is made.
    export COCKPIT_ANTHROPIC_API_KEY=...        # in your shell, never in the env file
    .venv/bin/python scripts/retail_cockpit/check_live.py

    # 2. Start WITHOUT RETAIL_COCKPIT_OFFLINE.
    launchers/retail/start-retail-candidate.command

Three things to know before you do:

* **Starting makes two `count_tokens` calls** (`verify_live`, once in
  `create_app` and once in the candidate bootstrap). Not billed, but real
  requests: a wrong model id or a credential the account cannot use fails the
  runtime at startup rather than on the first question.
* **`check_ready.py` skips its question in live mode**, because it submits a
  real analysis and the launcher runs it on every start. So READY proves the
  API, the book, the boundary and the stream, and says plainly that the
  question step was skipped. `--allow-paid-run` spends one on purpose.
* **The cumulative cap is `RETAIL_COCKPIT_SPEND_CAP_USD`**, enforced by the
  proxy against the engine's own ledger. The engine itself bounds only one
  run at a time. Unset it and there is no cap at all.

Rehearse the runner first -- it costs nothing and refuses to point at a live
engine:

    RETAIL_COCKPIT_OFFLINE=1 launchers/retail/start-retail-candidate.command
    .venv/bin/python scripts/retail_cockpit/run_uat.py --rehearse

Then the twelve, live:

    .venv/bin/python scripts/retail_cockpit/run_uat.py --i-accept-the-cost

It refuses to start unless `check_live.py` is satisfied, writes
`docs/retail_cockpit/evidence/live_uat.json` after every question, stops at
the cap, stops on question 2 failing and stops on a containment failure, and
resumes with `--from N` so a stop never costs what was already paid for.

The model is `claude-opus-5` and the card is
`config/cockpit_v4/price_card.candidate.json`, at Anthropic's published
first-party rates. If you bill through Bedrock or Google Cloud, hold a
discount, or pin US-only inference, those rates are wrong for you.

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
| Browser (five cycles, 135 checks) | `CANDIDATE_CYCLES=5 CANDIDATE_UI_URL=http://localhost:5329 CANDIDATE_API_URL=http://127.0.0.1:8329 CANDIDATE_ENGINE_URL=http://127.0.0.1:8415 node tests/retail_cockpit/browser/candidate.browser.mjs` |
| Memory | `.venv/bin/python scripts/retail_cockpit/benchmark_session.py --limits 1536MB,2048MB --repeat 3` |
| Live preflight (no provider call) | `.venv/bin/python scripts/retail_cockpit/check_live.py` |
| UAT rehearsal (no provider call) | `RETAIL_COCKPIT_OFFLINE=1 .venv/bin/python scripts/retail_cockpit/run_uat.py --rehearse` |
| The twelve, live (SPENDS MONEY) | `.venv/bin/python scripts/retail_cockpit/run_uat.py --i-accept-the-cost` |

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

---

# Mac acceptance

One sequence, for the isolated clone at `~/CreditProbe_Candidate/retail-cockpit`.
It is deterministic: `RETAIL_COCKPIT_OFFLINE=1` gives the engine a provider that
cannot reach the network, so **no paid provider call is possible** anywhere in it.

What it does not do, by construction:

- `/Users/tuhinchatterjee/Desktop/IPM_V2` is **read** by `rsync`, to seed the
  candidate's own copy of the book, and never written; nothing at run time
  points at it.
- `START_CREDITPROBE_RETAIL_DEMO.command` is not replaced, edited or opened, and
  no process the sequence did not start is stopped. The demo keeps its own
  database, lake, metadata, ports (5328/8328) and launcher, so it remains
  recoverable by double-clicking it exactly as today.
- No `reset --hard`, no force checkout, no `--overwrite`, no destructive
  cleanup. Step 2 **refuses** on a dirty tree and step 3 is fast-forward only,
  so a local edit stops the run rather than being discarded.
- The release is published into the **candidate's** lake
  (`var/retail-candidate-book/cockpit_v4_lake/`) and nowhere else, and
  `publish_release.py` refuses to overwrite one that exists.

Needs about 3 GB free: ~2 GB for the copy of the book, ~520 MB for the release.

Save it as `~/mac-acceptance.sh` and run `bash ~/mac-acceptance.sh`, so `set -e`
stops the run at the first thing that fails instead of carrying on.

```bash
# ── 0. where things are ──────────────────────────────────────────────────────
set -e
CAND=~/CreditProbe_Candidate/retail-cockpit
DEMO=/Users/tuhinchatterjee/Desktop/IPM_V2
#   The branch tip is the final candidate; step 2 verifies what it landed on.
BRANCH=claude/modest-rubin-cm037o
cd "$CAND"

# ── 1. refuse on a dirty tree: a local edit is yours, not mine to discard ────
if [ -n "$(git status --porcelain)" ]; then
  echo "The candidate clone has local changes. Stopping rather than discarding them:"
  git status --porcelain
  exit 1
fi

# ── 2. update to the pushed commit, fast-forward only ───────────────────────
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git merge --ff-only "origin/$BRANCH"     # refuses rather than rewriting
git rev-parse HEAD
#   -> must match the SHA I gave you for the final candidate

# ── 3. dependencies ─────────────────────────────────────────────────────────
uv sync
npm --prefix frontend ci

# ── 4. the candidate's OWN database (the demo's is untouched) ───────────────
createdb creditprobe_retail_candidate 2>/dev/null || true

# ── 5. configuration ────────────────────────────────────────────────────────
#   First run only. An existing .env.retail-candidate is left exactly as
#   it is -- these two lines are appended once, and a later one wins.
if [ ! -f .env.retail-candidate ]; then
  cp .env.retail-candidate.example .env.retail-candidate
  {
    echo ""
    echo "DATABASE_URL=postgresql+psycopg://$(whoami)@127.0.0.1:5432/creditprobe_retail_candidate"
    echo "SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')"
  } >> .env.retail-candidate
fi
set -a; . ./.env.retail-candidate; set +a
.venv/bin/python -m alembic upgrade head

# ── 6. the candidate's own copy of the published book (reads the demo only) ──
mkdir -p var/retail-candidate-book/analytics var/retail-candidate-book/metadata
rsync -a "$DEMO/data/retail/analytics/"  var/retail-candidate-book/analytics/
rsync -a "$DEMO/metadata/retail/"        var/retail-candidate-book/metadata/

# ── 7. publish the final immutable release, into the CANDIDATE lake ─────────
.venv/bin/python scripts/retail_cockpit/publish_release.py --revision 7
.venv/bin/python scripts/retail_cockpit/publish_release.py --revision 7 --verify

# ── 8. the numbers, against 28 independent oracles ──────────────────────────
.venv/bin/python scripts/retail_cockpit/check_oracles.py \
    --release cockpitdata-r1.2.0-c1.0.0-s20260910-p7

# ── 9. the port is still the port (291 files, C1 + C2 + F1) ─────────────────
.venv/bin/python scripts/retail_cockpit/verify_port.py

# ── 10. the safe memory benchmark. It REFUSES a limit this Mac cannot hold ──
.venv/bin/python scripts/retail_cockpit/benchmark_session.py \
    --limits 1536MB,2048MB --repeat 3
#   Reported ~3,033 MiB available -> leave COCKPIT_V4_SQL_MEMORY_LIMIT unset
#   (the engine's own 1536MB). Set 2048MB only if it reports >= 3,500 MiB free.

# ── 11. start it. No provider is reachable, so nothing can be charged ───────
RETAIL_COCKPIT_OFFLINE=1 launchers/retail/start-retail-candidate.command

# ── 12. verify the API, the engine and the whole Cockpit path ───────────────
.venv/bin/python scripts/retail_cockpit/check_ready.py \
    --api http://127.0.0.1:8329 --engine http://127.0.0.1:8415

# ── 13. verify the UI in a real browser, five cycles ────────────────────────
#   Playwright is NOT a dependency of the retail frontend -- this is an
#   acceptance harness, and adding a browser driver to the application's
#   package.json would change what the demo installs. Install it once,
#   globally, outside this repository. Skip if you already have it.
npm i -g playwright && npx playwright install chromium

CANDIDATE_CYCLES=5 \
CANDIDATE_UI_URL=http://localhost:5329 \
CANDIDATE_API_URL=http://127.0.0.1:8329 \
CANDIDATE_ENGINE_URL=http://127.0.0.1:8415 \
node tests/retail_cockpit/browser/candidate.browser.mjs
#   -> must print: 135 of 135 checks passed across 5 cycles
#   The harness finds Playwright itself (CANDIDATE_PLAYWRIGHT overrides) and
#   uses Playwright's own Chromium; it needs no browser path on the Mac.
```

**Then open:**

    http://localhost:5329

The Cockpit is the home page. The badge under it must read
*Retail Cockpit · Retail Credit · monthly · 25 months 2024-08–2026-08 ·
SAR million · cockpitdata-r1.2.0-c1.0.0-s20260910-p7*, every value from the
release. The banner says **READY (OFFLINE)** — the whole path works, and no
question can be answered, because no provider is configured. That is the
deterministic acceptance; the live UAT is a separate decision.

To stop it:

    launchers/retail/stop-retail-candidate.command

which stops only the pids the launcher wrote. The demo on 5328/8328 is
unaffected throughout and starts from its own `.command` as always.
