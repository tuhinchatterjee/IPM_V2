# Regression report

## Method

The V3 suite is the baseline. `backend/cockpit_agentic/` is **byte-identical**
to the base commit on this branch — `git diff 015de742890e HEAD --
backend/cockpit_agentic backend/api backend/llm backend/config.py` is empty —
so any difference in its results is environmental, and this report establishes
that rather than assuming it.

Failure **IDs and their material messages** are both compared. A new failure
hiding under an old failing test name is exactly what comparing IDs alone
misses.

## Environment

| | |
|---|---|
| Revision | `claude/cockpit-single-agent-v4-h8fsbq`, base `015de742890e895026ed8558822f4bff87ddd447` |
| Python | 3.11.15 |
| Platform | Linux container (hosted session), not the user's Mac |
| Data namespace | `cockpit_v4` for V4, `cockpit_agentic_v3` for the V3 run |
| Provider credential | **absent** — no paid call in any run below |

The container started with **no Python dependencies installed at all**.
Everything below was installed during this session to make the suites
runnable: `pytest fastapi pydantic duckdb pandas pyarrow httpx jsonschema
anthropic python-dotenv sqlalchemy openpyxl uvicorn psycopg[binary]
python-multipart python-docx`. None of that is a code change.

## V3 suite — the regression baseline

```
COCKPIT_AGENTIC_V3_NAMESPACE=cockpit_agentic_v3 \
  python3 -m pytest tests/cockpit_agentic -q
```

| Run | tests collected | passed | failures | errors | skipped |
|---|---:|---:|---:|---:|---:|
| Before dependency installs | 590 | 556 | 0 | 8 | 26 |
| After `psycopg[binary]` | 590 | 556 | 0 | 8 | 26 |
| After `python-multipart` | 590 | 556 | 0 | 8 | 26 |
| **After `python-docx`** | **590** | **564** | **0** | **0** | **26** |

The 8 errors were the same 8 tests throughout — all in
`tests/cockpit_agentic/test_thread_and_api.py`, all failing **on setup**, and
each run's message named the next missing dependency in a chain:
`psycopg` → `python-multipart` → `docx`. Each is imported while constructing
the full product FastAPI application, which those 8 tests need and no other
V3 test does.

Installing the third one cleared all eight. **V3 is fully green on the V4
branch: 590 collected, 0 failures, 0 errors, 26 skipped.**

The 26 skips are V3's own pre-existing skips and were identical in every run.

Re-run at handoff on the final commit: **564 passed, 26 skipped, 0 failed**
in 146s — identical to the baseline above.

**Conclusion: V4 introduces no V3 regression.** That is supported by two
independent facts — the V3 sources are unchanged, and the V3 suite passes
completely once this container has the dependencies the suite has always
needed.

The previously reported "413 failures and 231 setup errors" is a historical
report from a different environment. It is not used as a pass criterion here,
and this environment did not reproduce it.

## V4 suite

```
COCKPIT_AGENTIC_V3_NAMESPACE=cockpit_v4 python3 -m pytest tests/cockpit_v4 -q
```

| tests collected | passed | failures | errors | skipped | elapsed |
|---:|---:|---:|---:|---:|---:|
| 292 | 292 | 0 | 0 | 0 | ~8 s |

Frontend unit suite — the whole thing, not only the Cockpit:

```
cd frontend && npm test
```

| suites | tests | pass | fail |
|---:|---:|---:|---:|
| 38 | 459 | 459 | 0 |

The Cockpit V4 components alone are 51 of those:

```
cd frontend && node --test --experimental-strip-types \
  "src/components/cockpit-v4/*.test.ts"
```

covering `reducer.test.ts`, `client.test.ts`, `live-trace.test.ts` and
`markdown.test.ts`.

## Defects found and fixed while testing

Each was found by a test that failed for the right reason, not by review:

| # | Defect | Consequence had it shipped |
|---|---|---|
| 1 | A common table expression was read as an unauthorized relation. | Every legitimate multi-step SQL analysis refused. Found by the Stage-2 case. |
| 2 | An idempotent retry was rejected as a concurrent run, because the concurrency check ran before the idempotency lookup. | A dropped 202 would come back as a 409 the caller could not clear. |
| 3 | `_ps` skipped a header that `ps -o field=` does not print, so every process looked dead. | The **stop script would refuse to stop anything**. Found by the reused-pid test. |
| 4 | `NO_PROGRESS` ended the run instead of rejecting that submission. | Work that had already succeeded was thrown away. |
| 5 | A corrupt state database raised a raw `sqlite3.DatabaseError`. | An unclassified internal failure instead of the declared `STORAGE_UNAVAILABLE`, sending an operator to the wrong place. |
| 6 | The loopback demo principal used a hard-coded tenant that the seeded release does not contain. | Every analysis would read zero rows — "the portfolio is empty" rather than "wrong tenant". Found by the real-socket run. |

### Second round — the launcher/frontend wiring

| # | Defect | Consequence had it shipped |
|---|---|---|
| 7 | The launcher set `NEXT_PUBLIC_COCKPIT_V4_API` but not `NEXT_PUBLIC_API_URL`. | The Cockpit talked to the V4 API while the header, the status badge and every landing-page widget talked to `http://127.0.0.1:8000` — a backend the V4 instance never starts. |
| 8 | The V4 API served no `/api/v1/health`, so pointing the shell at it produced a 404. | The header rendered **"Backend offline"** while V4 was answering every request — the status indicator lying about the service next to it. |
| 9 | `wait_for_health` JSON-decoded the UI's root page, which serves HTML. | The decode raised, was swallowed as "not ready yet", and a healthy UI was reported as failed until the timeout expired. |
| 10 | The V4 client resolved an unset address to `""` (same origin). | A silent wrong address rather than a stated one. It now has no default at all. |

### Third round — the Cockpit page was still the legacy one

| # | Defect | Consequence |
|---|---|---|
| 11 | `frontend/src/app/page.tsx` rendered the legacy Cockpit. The V4 component existed and was imported by nothing. | Pressing Ask ran the legacy flow: `POST /api/v1/investigations` and `/api/v1/agentic/officer`, both 404 against the V4 API. **Opus V4 was never reached.** |
| 12 | Shell chrome polled `/demo`, `/auth/me`, `/ai/status` and `/workspace/notifications`. | Four 404s per page load in the V4 API log, obscuring the Cockpit under test. |
| 13 | The replay effect aborted its own async work under React StrictMode's double mount. | A browser refresh silently failed to reconnect to the running run. |
| 14 | The stub's "slow" case blocked 30s inside one `converse`. | Made a correct implementation look broken: V4 observes a cancellation *between* actions and does not abort an in-flight provider call — that is what the deadline and supervisor are for. Fixed in the test, not the product. |

### Fourth round — the false process trace, the tool contract, and Product Help

| # | Defect | Consequence |
|---|---|---|
| 15 | `client.ts` registered only `source.onmessage`. The server sends **named** SSE frames (`event: run.progress`), and a named frame never reaches `onmessage`. | The live process panel was a **false trace**: a run that really executed 15 events for 29.4s displayed "not started" and "Answered in 0s". The panel was reporting on a stream it was not receiving. Fixed by registering a listener for each of the 22 names in `backend/cockpit_v4/events.py`, with a `seq` guard against replays. |
| 16 | `finalize_response` advertised `clarification_question` as `["string","null"]` but the server validator demanded `str`. | A model that followed the published schema had its **answer rejected** on the null. Fixed at the boundary: the validator now accepts absent-as-null for every optional field across all tools, while mandatory fields still fail closed. Prompt wording was not used. |
| 17 | `execute_analysis`'s schema declared `expected_units` an **object**; the parser demanded a **string**. | A model following the schema would have had *every* analysis submission rejected. Found by mechanically diffing each published schema against its parser (`test_tool_contract_agreement.py`). |
| 18 | Elapsed time was computed client-side from wall clock. | A refresh mid-run restarted the timer at 0. The panel now reads `budget.elapsed_seconds` from the run status when the run is settled, and marks it authoritative. |
| 19 | Sub-second stages rendered as "0s". | A real 0.4s stage looked like it had not run. `formatSeconds` keeps one decimal below 10s. |
| 20 | A later successful attempt replaced the failed one in the panel. | The trace hid that anything had gone wrong. `Step.failures` is now incremented and never cleared; the panel keeps the failed substep visible under a succeeded step. |
| 21 | Product Help had no grounded source. | Answers about CreditProbe were the model's guess. A versioned **Product Knowledge Pack** (`backend/cockpit_v4/product_knowledge.json`, pack `2026-09-11.1`, source SHA256 `bdb3ce5d…`) is now ingested from the deck, with a ~924-token synopsis always in base context and a fifth tool, `inspect_product_knowledge`, for selective retrieval. The deck is never attached wholesale. |
| 22 | Keyword retrieval matched substrings: `"kpi"` matched inside **"cockpit"**. | Irrelevant sections retrieved on almost every question. Fixed with a leading word-boundary pattern (a both-sides boundary was also wrong — it made "layers" and "automatically" miss). |
| 23 | Answers were rendered as plain text. | Markdown arrived as raw `**` and `-` characters. Now parsed to a React element tree — no HTML string is produced, so there is nothing to sanitize and no new dependency was added. |
| 24 | `markdown.ts` and `markdown.tsx` shared a stem. `tsc` resolved `./markdown` to the `.ts`; **Turbopack resolved it to the `.tsx` itself**, a self-import. | The page failed to build while every type check passed. Only running the app caught it. Renamed to `markdown-parse.ts`. |

Slide 14 of the deck describes a **multi-agent** design. It is recorded in the
pack as `historical_architecture`, `status: HISTORICAL_ARCHITECTURE`,
`label: NOT_CURRENT_V4_ARCHITECTURE`, `applies_to_current_runtime: false`, and
is deliberately **not retrievable**, so the analyst cannot describe the current
runtime as multi-agent.

### Browser suite

```
python3 scripts/cockpit_v4/browser_evidence.py
```

Real Chromium, real Next.js UI, real V4 API, **stubbed analyst**. 14/14 pass.
Every network request the page makes is recorded, so "never calls the legacy
flow" is checked rather than asserted. A screenshot of a rendered answer is
written to `docs/cockpit_v4/evidence/cockpit_v4_answer.png`.

## Suite results at handoff

All run in this container, in this order, on the commit being handed off.

| Suite | Command | Result |
|---|---|---:|
| V4 backend | `python3 -m pytest tests/cockpit_v4` | **292 passed**, 0 failed |
| — launcher + frontend wiring subset | `… test_launcher_safety.py test_frontend_wiring.py` | 43 passed |
| — Product Help benchmark | `… test_product_help_benchmark.py` | 81 passed |
| — tool contract agreement | `… test_tool_contract_agreement.py` | 26 passed |
| — event contract parity | `… test_event_contract_parity.py` | 5 passed |
| — "Who are you?" acceptance | `… test_who_are_you_acceptance.py` | 7 passed |
| Frontend unit | `npm test` (`node --test`, 38 suites) | **459 passed**, 0 failed |
| — Cockpit V4 components only | `node --test 'src/components/cockpit-v4/*.test.ts'` | 51 passed |
| Browser (real Chromium) | `python3 scripts/cockpit_v4/browser_evidence.py` | **14/14 passed** |
| V3 regression | `python3 -m pytest tests/cockpit_agentic` | **564 passed**, 26 skipped, 0 failed |
| Acceptance coverage | `python3 scripts/cockpit_v4/acceptance_evidence.py` | 100 / 100 covered |

The V3 result is the material one for isolation: `backend/cockpit_agentic/` is
unchanged on this branch and its suite is green.

Two design rules were also refined because a test showed the original was
wrong, not because a test was inconvenient:

- A **partial answer** that states plainly what it could not establish is now
  accepted with no numeric claim. Only a full `answer` must carry bound
  evidence. Refusing an honest concession was the wrong behaviour.
- `NO_PROGRESS` now returns to the analyst as a submission-level rejection, so
  a supported partial answer is still reachable.

## What was NOT run

- **The 84-question bank.** Not run, per the instruction, and not run
  automatically by anything in this build.
- **Any paid live provider call.** No credential was authorized in this
  environment. Every acceptance case's `real_provider` field reads `NOT RUN`,
  and the browser suite runs against a **stubbed analyst** — it proves the
  delivery path, not the model's answers.
- **Python analysis.** `pyrunner.probe()` reports the capability unavailable
  in this container: the escape self-test found network access was not
  blocked, so the runner refuses to certify itself.
- **The full repository suite.** Only `tests/cockpit_agentic` and
  `tests/cockpit_v4` were run, plus the frontend unit suite. This report makes
  no claim about the rest of the repository.
