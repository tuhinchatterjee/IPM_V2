# Cockpit V4 runbook (macOS)

Three commands. No pid hunting, no `lsof`, no `kill -9`.

## Once, before the first start

**1. Get the code**

```bash
cd /path/to/IPM_V2
git fetch origin claude/cockpit-single-agent-v4-h8fsbq
git worktree add ../cockpit_v4 claude/cockpit-single-agent-v4-h8fsbq
cd ../cockpit_v4
```

A separate worktree, so nothing you have running from the V3 checkout is
affected. Do **not** switch branches in a directory that is serving a live
frontend — file changes reach a running dev server even without a restart.

**2. Install dependencies** (in whatever environment you already use)

```bash
pip install -r requirements.txt
pip install uvicorn duckdb pandas pyarrow httpx
cd frontend && npm install && cd ..
```

**3. Store the key once** (optional, and the only way to avoid a prompt)

```bash
security add-generic-password -s creditprobe-cockpit-v4 -a "$USER" -w
```

Paste the key at the hidden prompt. It goes into the Keychain, not into the
repository, not into your shell history, and never into a chat window.

**4. Replace the price-card placeholder** — required before any paid run

Edit `config/cockpit_v4/price_card.json`. Replace
`REPLACE-WITH-YOUR-MODEL-ID` with your exact model id and fill in all four
billing classes from the current published schedule, plus `verified_at`.

Until you do, V4 starts, reports `CAPABILITY_UNVERIFIED`, and refuses to make
a paid request. That is deliberate: an "enforced" cost badge over an unknown
price is a false claim.

**5. Seed the isolated V4 release** (once)

```bash
python3 scripts/cockpit_v4/seed_release.py --release v4-uat-20q-v1
```

Writes into the `cockpit_v4` namespace only. It refuses the V3 namespace, and
refuses to overwrite an existing release unless you pass `--overwrite`
deliberately.

## Every day

| Do this | Double-click | Or run |
|---|---|---|
| Start | `scripts/cockpit_v4/START_COCKPIT_V4.command` | `python3 scripts/cockpit_v4/start.py` |
| Check | `scripts/cockpit_v4/STATUS_COCKPIT_V4.command` | `python3 scripts/cockpit_v4/status.py` |
| Stop | `scripts/cockpit_v4/STOP_COCKPIT_V4.command` | `python3 scripts/cockpit_v4/stop.py` |

`start` prints the URL and opens it. Default ports **8414** (API) and **5414**
(UI).

### What start does, in order

1. Confirms the worktree and records the **startup** SHA — read once, so the
   trace names the code the process is running.
2. Confirms no V4 instance of ours is already up.
3. Finds free ports. **A busy port is reported with who holds it and an
   alternative is chosen. Nothing is ever stopped to free a port** — the
   occupant may be your V3 demo.
4. Obtains the key from the environment, then the Keychain, then a hidden
   prompt.
5. Verifies the model, its capabilities and its price **without a paid call**.
6. Opens the release read-only.
7. Starts the API, waits for real health, starts the UI, waits for it, prints
   a diagnostics table and the URL.

Any step failing stops there and says which setting to fix.

### What the UI is told, and why it is two variables

The V4 frontend process is given **both** API addresses, at the port the
launcher actually selected:

| Variable | Read by | Why it matters |
|---|---|---|
| `NEXT_PUBLIC_COCKPIT_V4_API` | the Cockpit V4 client | the runs, the event stream, cancellation |
| `NEXT_PUBLIC_API_URL` | the application shell and `lib/api.ts` | the header, the backend-status badge, the landing-page widgets |

Setting only the first was a real defect: the Cockpit talked to 8414 while the
header and every landing widget kept talking to `http://127.0.0.1:8000`, a
backend the V4 instance never started. Half the page then reported a system
that was not there.

Both are set **for the V4 UI process only**. The default inside `lib/api.ts`
is untouched, so every other CreditProbe instance behaves exactly as before.

The V4 Cockpit client has no default address at all. If
`NEXT_PUBLIC_COCKPIT_V4_API` is missing it says so plainly rather than
borrowing the shell's variable — there is nothing for it to silently fall back
*to*.

### What the Cockpit page is, in V4 mode

When `NEXT_PUBLIC_COCKPIT_V4_API` is set, `/` renders the **Cockpit V4** Ask
surface: a question box, a Standard/Deep control, Ask, Stop, a hideable
**Show process / Hide process** panel driven by the backend's own persisted
events, the final answer, links to the artifacts a figure was read from, and
an explicit terminal failure with a support reference.

The legacy Cockpit page is not rendered at all in this mode — which is the
point. It opens with four `useAsync` calls to `/ask/suggestions`, `/ask/mode`,
`/ask/briefing` and `/investigations`, and React fires a component's hooks the
moment it mounts. Guarding the JSX would not have stopped those requests;
declining to instantiate the component does.

Asking runs the V4 lifecycle end to end:
`POST /runs` → `run_id` → the process panel appears → the browser subscribes to
`/runs/{run_id}/events` → `GET /runs/{run_id}` for authoritative state →
the answer renders. Stop calls `/runs/{run_id}/cancel`. A browser refresh
reconnects to the **same** run from the last sequence it rendered — it does not
ask again.

Widgets whose backend is not part of this runtime (risk cases, investigations,
early warning, the briefing, workspace notifications) render a neutral "not
available in this isolated V4 runtime" state and **make no request at all**.

### What the status badge will say

The header polls `/api/v1/health`, which the V4 API now serves about itself.
You should see:

> **CreditProbe Cockpit V4 reachable · dashboard service not in this runtime**

That is the honest reading. This instance runs the Cockpit API only; the
landing-page widgets, briefing, threads and dashboard routes are served by the
main CreditProbe backend, which this instance does not start. The system-status
panel lists them as **Not configured** with that explanation.

"Backend offline" now means what it says: the V4 API did not answer. A genuine
V4 fault — an unreadable release, an unwritable state store — still turns the
headline red, because the distinction has to cut both ways or it is just a
green light.

### What stop does

It stops a process only when **all four** still match what V4 recorded when it
started it: the pid exists, its start time is within seconds of the record,
its command line is the one V4 launched, and its working directory is the V4
worktree. Anything failing a check is **reported and left alone** — on a busy
Mac that pid now belongs to something else.

SIGTERM to the process group V4 created, then SIGKILL only to a group that
ignored it. There is no `pkill`, no `kill $(lsof -ti:8414)` and no pid chosen
with `tail -1`.

## Reading the diagnostics table

Three **separate** readiness flags, deliberately not one badge:

| Flag | Needs |
|---|---|
| `ready_for_product_help` | credential + model + verified price + state database |
| `ready_for_sql_analysis` | the above, plus the release opening |
| `ready_for_python_analysis` | the above, plus an isolated Python runner that passes its own escape self-test |

`ready_for_python_analysis: false` is normal on a stock Mac without a
container. SQL analysis is unaffected. A Python step will fail with
`PYTHON_UNAVAILABLE` and will **not** be quietly rewritten as SQL.

Live at `http://127.0.0.1:8414/api/v1/cockpit-v4/diagnostics`.

## When something goes wrong

| Symptom | What it means | What to do |
|---|---|---|
| `COCKPIT_ANTHROPIC_API_KEY is not available` | The Cockpit's own key is not set. V4 will not use another module's key. | Set it, or store it in the Keychain (step 3). |
| `CAPABILITY_UNVERIFIED` | The price card has no verified entry for your model. | Step 4. No paid request runs until then. |
| `DATA_UNAVAILABLE` | The pinned release is not readable. Another release is a different book, so nothing is substituted. | Step 5, or set `COCKPIT_V4_RELEASE_ID`. |
| `port 8414 is in use … NOT stopped` | Something else has the port. | Let it pick the alternative it names, or pass `--api-port`. |
| The panel shows `CONNECTION_LOST` | **This browser** stopped receiving updates. It says nothing about the run. | Click "Check its status". The answer is persisted; it is not lost and does not need re-asking. |
| A run ends `INTERRUPTED` | The worker stopped and the supervisor settled it. Nothing was replayed, because a paid call may already have happened. | Ask again; it is a new run. Any results already produced are preserved. |
| A run ends `EXPIRED` | The deadline passed. | Use Deep mode, or narrow the question. |
| An answer shows a support reference | An application defect, recorded with its operation. | Quote the reference. Rephrasing will not help. |

Logs: `$COCKPIT_V4_RUNTIME_DIR/logs/{api,ui}.log`, default
`~/.creditprobe/cockpit_v4/logs`.

## Running the browser suite

A real Chromium against the real UI and a stubbed analyst. It starts and stops
everything it needs on free ports:

```bash
python3 scripts/cockpit_v4/browser_evidence.py
```

Evidence lands in `docs/cockpit_v4/evidence/browser.json`. Add `--keep-up` to
leave the stack running afterwards for manual poking — and remember to stop it.

The analyst is a **stub**. The suite proves the wiring, the run lifecycle and
the rendering. It is not a live Opus validation.

## Settings

| Variable | Meaning |
|---|---|
| `COCKPIT_AGENTIC_V4` | The V4 switch. Does **not** enable or alter V3. |
| `AI_PROVIDER` | Supported provider; `anthropic`. |
| `AI_COCKPIT_REASONING_MODEL` | The analyst model id. No default, no `latest`, no inheriting `AI_MODEL`. |
| `COCKPIT_ANTHROPIC_API_KEY` | The only credential. Reported as PRESENT/MISSING only. |
| `COCKPIT_V4_RUNTIME_DIR` | Private state, artifacts, logs, pid records. |
| `COCKPIT_V4_STATE_DATABASE` | State database; secret-bearing URLs are redacted in diagnostics. |
| `COCKPIT_V4_RELEASE_ID` | The pinned authorized release. |
| `COCKPIT_V4_API_PORT` / `COCKPIT_V4_UI_PORT` | 8414 / 5414. Verified, never forcibly freed. |
| `COCKPIT_V4_LOCAL_DEMO_AUTH` | Loopback synthetic-only profile. Off outside it. |
| `COCKPIT_V4_PRICE_CARD` | Versioned non-secret price/capability metadata. |
| `COCKPIT_V4_MEMORY_ENABLED` | False for UAT. |
| `COCKPIT_V4_MEMORY_MODEL` | Required only when memory summarization is on. |
| `COCKPIT_V4_PYTHON_RUNNER` | Enables the Python capability *probe*. The self-test still has to pass. |

`.env.example` carries these names with harmless placeholders.

## What V4 never touches

Docker, EWS, What-if, Playbook, Planner, Lenses, any presentation instance,
the V3 branch, the V3 namespace, published releases, `data/curated`,
`data/raw`, `metadata`, or `data/analytics`. `config.check_write_target`
refuses a write outside the V4 runtime directory before the first byte.
