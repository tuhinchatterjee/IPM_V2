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
| 167 | 167 | 0 | 0 | 0 | ~8.2 s |

Frontend reducer:

```
cd frontend && node --test --experimental-strip-types \
  "src/components/cockpit-v4/reducer.test.ts"
```

| tests | pass | fail |
|---:|---:|---:|
| 23 | 23 | 0 |

Run as:

```
cd frontend && node --test --experimental-strip-types \
  "src/components/cockpit-v4/reducer.test.ts" \
  "src/components/cockpit-v4/client.test.ts" \
  "src/components/system/runtime-surfaces.test.ts"
```

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
  environment. Every acceptance case's `real_provider` field reads `NOT RUN`.
- **A real browser.** The delivery path was exercised over real sockets with a
  real SSE client (`scripts/cockpit_v4/live_path_evidence.py`); the panel's
  rendering is covered by reducer unit tests. A Playwright pass against the
  running UI is outstanding.
- **Python analysis.** `pyrunner.probe()` reports the capability unavailable
  in this container: the escape self-test found network access was not
  blocked, so the runner refuses to certify itself.
- **The full repository suite.** Only `tests/cockpit_agentic` and
  `tests/cockpit_v4` were run. This report makes no claim about the rest of
  the repository.
